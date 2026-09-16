import logging

import math
from datetime import datetime, timezone, timedelta


from app.modules.post.data.models import Post, PostLike, PostSave, PostView
from app.modules.post.domain.interfaces.repository import IPostRepository
from app.modules.post.domain.exceptions import PostNotFoundError
from app.modules.post.application.schemas import (
    PostResponse, PostDealResponse, FeedPostCard, MyPostCard,
    MyPostFeedResponse, PostFeedResponse, SavedPostFeedResponse, FollowingFeedResponse,
)
from app.modules.post.recommendation import service as rec_service
from app.modules.post.recommendation.models import SeenPost
from app.modules.post.recommendation.constants import FRESH_BOOST_PEAK, FRESH_DECAY_TAU, _ROLE_NAMES
from app.shared.utils.time_decay import freshness_boost
from app.modules.post.recommendation.session_taste import service as interaction_service
from app.modules.post.recommendation.session_taste.constants import CATEGORY_NAMES

log = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _active_profile_ids(repo: IPostRepository) -> list[int]:
    return repo.active_profile_ids()


def _is_liked(repo: IPostRepository, post_id: int, profile_id: int) -> bool:
    return repo.is_liked(post_id, profile_id)


def _is_saved(repo: IPostRepository, post_id: int, profile_id: int) -> bool:
    return repo.is_saved(post_id, profile_id)


def _to_post_response(repo: IPostRepository, post: Post, viewer_profile_id: int) -> PostResponse:
    return PostResponse(
        id=post.id,
        profile_id=post.profile_id,
        category_id=post.category_id,
        commodity_id=post.commodity_id,
        title=post.title,
        caption=post.caption,
        image_urls=post.image_urls,
        source_url=post.source_url,
        location_name=post.location_name,
        latitude=post.latitude,
        longitude=post.longitude,
        is_public=post.is_public,
        target_roles=post.target_roles,
        allow_comments=post.allow_comments,
        deal_details=PostDealResponse.model_validate(post.deal_details) if post.deal_details else None,
        created_at=post.created_at,
        is_liked=_is_liked(repo, post.id, viewer_profile_id),
        is_saved=_is_saved(repo, post.id, viewer_profile_id),
        view_count=post.view_count,
        like_count=post.like_count,
        comment_count=post.comment_count,
        share_count=post.share_count,
        save_count=post.save_count,
    )


def _batch_post_responses(
    repo: IPostRepository,
    posts: list[Post],
    viewer_profile_id: int,
) -> list[PostResponse]:
    """Build PostResponse objects for a list of posts using batch DB lookups."""
    if not posts:
        return []

    post_ids = [p.id for p in posts]

    liked_ids = repo.liked_post_ids(viewer_profile_id, post_ids)
    saved_ids = repo.saved_post_ids(viewer_profile_id, post_ids)

    return [
        PostResponse(
            id=post.id,
            profile_id=post.profile_id,
            category_id=post.category_id,
            commodity_id=post.commodity_id,
            title=post.title,
            caption=post.caption,
            image_urls=post.image_urls,
            source_url=post.source_url,
            location_name=post.location_name,
            latitude=post.latitude,
            longitude=post.longitude,
            is_public=post.is_public,
            target_roles=post.target_roles,
            allow_comments=post.allow_comments,
            deal_details=PostDealResponse.model_validate(post.deal_details) if post.deal_details else None,
            created_at=post.created_at,
            is_liked=post.id in liked_ids,
            is_saved=post.id in saved_ids,
            view_count=post.view_count,
            like_count=post.like_count,
            comment_count=post.comment_count,
            share_count=post.share_count,
            save_count=post.save_count,
        )
        for post in posts
    ]


def batch_feed_cards(
    repo: IPostRepository,
    posts: list[Post],
    viewer_profile_id: int,
    viewer_users_id=None,
) -> list[FeedPostCard]:
    """Build FeedPostCard objects with full author info and following status."""
    if not posts:
        return []

    post_ids = [p.id for p in posts]
    author_profile_ids = list({p.profile_id for p in posts})

    liked_ids = repo.liked_post_ids(viewer_profile_id, post_ids)
    saved_ids = repo.saved_post_ids(viewer_profile_id, post_ids)

    authors = repo.get_authors_with_business(author_profile_ids)

    if viewer_users_id is None:
        viewer_users_id = repo.get_user_id_for_profile(viewer_profile_id)

    following_user_ids: set = set()
    if viewer_users_id:
        candidate_uids = [a.users_id for a in authors.values() if a.users_id]
        if candidate_uids:
            following_user_ids = repo.following_user_ids(viewer_users_id, candidate_uids)

    cards = []
    for post in posts:
        author = authors.get(post.profile_id)
        biz = author.business if author else None
        cards.append(FeedPostCard(
            id=post.id,
            profile_id=post.profile_id,
            category_id=post.category_id,
            commodity_id=post.commodity_id,
            title=post.title,
            caption=post.caption,
            image_urls=post.image_urls,
            source_url=post.source_url,
            location_name=post.location_name,
            location_city=biz.city if biz else None,
            location_state=biz.state if biz else None,
            allow_comments=post.allow_comments,
            deal_details=PostDealResponse.model_validate(post.deal_details) if post.deal_details else None,
            created_at=post.created_at,
            is_liked=post.id in liked_ids,
            is_saved=post.id in saved_ids,
            like_count=post.like_count,
            comment_count=post.comment_count,
            author_name=author.name if author else "",
            author_role=_ROLE_NAMES.get(author.role_id, "Trader") if author else "Trader",
            author_user_id=str(author.users_id) if author else "",
            author_company=biz.business_name if biz else None,
            author_avatar_url=author.avatar_url if author else None,
            is_following=bool(author and author.users_id in following_user_ids),
            is_user_verified=author.is_user_verified if author else False,
            is_business_verified=author.is_business_verified if author else False,
        ))
    return cards


def _batch_my_post_cards(
    repo: IPostRepository,
    posts: list[Post],
    profile_id: int,
) -> list[MyPostCard]:
    """Build MyPostCard objects for the owner's own posts feed."""
    if not posts:
        return []

    post_ids = [p.id for p in posts]

    liked_ids = repo.liked_post_ids(profile_id, post_ids)
    saved_ids = repo.saved_post_ids(profile_id, post_ids)

    author = repo.get_profile_with_business(profile_id)
    biz = author.business if author else None

    cards = []
    for post in posts:
        cards.append(MyPostCard(
            id=post.id,
            profile_id=post.profile_id,
            category_id=post.category_id,
            commodity_id=post.commodity_id,
            title=post.title,
            caption=post.caption,
            image_urls=post.image_urls,
            source_url=post.source_url,
            allow_comments=post.allow_comments,
            deal_details=PostDealResponse.model_validate(post.deal_details) if post.deal_details else None,
            location_name=post.location_name,
            location_city=biz.city if biz else None,
            location_state=biz.state if biz else None,
            like_count=post.like_count,
            comment_count=post.comment_count,
            is_liked=post.id in liked_ids,
            is_saved=post.id in saved_ids,
            created_at=post.created_at,
            is_public=post.is_public,
            target_roles=post.target_roles,
            view_count=post.view_count,
            share_count=post.share_count,
            save_count=post.save_count,
            author_name=author.name if author else "",
            author_role=_ROLE_NAMES.get(author.role_id, "Trader") if author else "Trader",
            author_user_id=str(author.users_id) if author else "",
            author_company=biz.business_name if biz else None,
            author_avatar_url=author.avatar_url if author else None,
            is_following=False,
            is_user_verified=author.is_user_verified if author else False,
            is_business_verified=author.is_business_verified if author else False,
        ))
    return cards


def _score_following_posts(
    posts: list[Post],
    viewer_commodity_ids: set[int],
    taste_counts: dict[str, float],
) -> list[tuple[Post, float]]:
    total_taste = sum(math.log1p(v) for v in taste_counts.values()) or 1.0
    results = []
    for post in posts:
        commodity_boost = 1.3 if post.commodity_id in viewer_commodity_ids else 1.0

        cat_key = CATEGORY_NAMES.get(post.category_id, "")
        cat_w = math.log1p(taste_counts.get(cat_key, 0)) / total_taste

        freshness = freshness_boost(post.created_at, FRESH_BOOST_PEAK, FRESH_DECAY_TAU)

        closed_penalty = 0.5 if (post.deal_details and post.deal_details.is_closed) else 1.0

        engagement = math.log1p(post.like_count * 2 + post.save_count * 3 + post.comment_count)
        score = (0.5 + cat_w) * commodity_boost * freshness * closed_penalty * (1.0 + 0.05 * engagement)
        results.append((post, score))
    return results


def _get_post_or_raise(repo: IPostRepository, post_id: int) -> Post:
    post = repo.get_active_post(post_id)
    if not post:
        raise PostNotFoundError(f"Post {post_id} not found")
    return post


# ----------------------------------------------------------------------------
# Views
# ----------------------------------------------------------------------------

def _record_view(repo: IPostRepository, post_id: int, profile_id: int) -> None:
    if not repo.record_first_view(post_id, profile_id):
        # Already seen — a revisit is its own signal, not another view.
        interaction_service.record_revisit_event(repo.session, profile_id, post_id)


# ----------------------------------------------------------------------------
# Get / Feed functions
# ----------------------------------------------------------------------------

def get_post(repo: IPostRepository, post_id: int, viewer_profile_id: int) -> PostResponse:
    post = _get_post_or_raise(repo, post_id)
    _record_view(repo, post_id, viewer_profile_id)
    repo.refresh(post)
    try:
        rec_service.record_seen(repo.session, viewer_profile_id, [post_id])
    except Exception:
        log.exception("record_seen failed for profile %s on post %s", viewer_profile_id, post_id)
    return _to_post_response(repo, post, viewer_profile_id)


def get_feed(repo: IPostRepository, viewer_profile_id: int, limit: int = 20, offset: int = 0) -> list[PostResponse]:
    posts = repo.list_active_posts(limit, offset)
    return _batch_post_responses(repo, posts, viewer_profile_id)


def get_my_posts(
    repo: IPostRepository,
    profile_id: int,
    limit: int = 20,
    cursor_post_id: int | None = None,
) -> MyPostFeedResponse:
    query = (
        repo.list_my_posts(profile_id, cursor_post_id, limit)
    )
    posts = query
    next_cursor = posts[-1].id if len(posts) == limit else None
    return MyPostFeedResponse(
        posts=_batch_my_post_cards(repo, posts, profile_id),
        next_cursor=next_cursor,
    )


def get_following_feed(
    repo: IPostRepository,
    profile_id: int,
    limit: int = 20,
    cursor_post_id: int | None = None,
) -> FollowingFeedResponse:
    profile = (
        repo.get_profile_with_commodities(profile_id)
    )
    if not profile:
        return FollowingFeedResponse(posts=[], all_caught_up=False)

    followed_profile_ids = repo.followed_profile_ids(profile.users_id)
    if not followed_profile_ids:
        return FollowingFeedResponse(posts=[], all_caught_up=False)

    seen_ids: set[int] = repo.seen_post_ids(profile_id)

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    posts = repo.list_following_posts(followed_profile_ids, cutoff, seen_ids)

    three_day_cutoff = datetime.now(timezone.utc) - timedelta(days=3)
    recent_unseen = [
        p for p in posts
        if (p.created_at if p.created_at.tzinfo else p.created_at.replace(tzinfo=timezone.utc))
        >= three_day_cutoff
    ]
    all_caught_up = False
    if not recent_unseen and seen_ids:
        all_caught_up = repo.has_seen_recent_followed_post(
            followed_profile_ids, three_day_cutoff, seen_ids
        )

    # Same store the recommendation feed ranks on — the two feeds disagreed
    # while this read the legacy user_taste_profiles counters.
    taste_counts = repo.get_category_taste_weights(profile_id, profile.role_id)
    viewer_commodity_ids = {pc.commodity_id for pc in profile.commodities}
    scored = _score_following_posts(posts, viewer_commodity_ids, taste_counts)
    scored.sort(key=lambda x: x[1], reverse=True)

    start = 0
    if cursor_post_id is not None:
        ranked_ids = [p.id for p, _ in scored]
        try:
            start = ranked_ids.index(cursor_post_id) + 1
        except ValueError:
            start = 0

    page_posts = [p for p, _ in scored[start: start + limit]]
    next_cursor = page_posts[-1].id if len(page_posts) == limit else None

    return FollowingFeedResponse(
        posts=batch_feed_cards(repo, page_posts, profile_id, viewer_users_id=profile.users_id),
        all_caught_up=all_caught_up,
        next_cursor=next_cursor,
    )


def get_saved_posts(
    repo: IPostRepository,
    profile_id: int,
    limit: int = 20,
    cursor_save_id: int | None = None,
) -> SavedPostFeedResponse:
    query = (
        repo.list_saves(profile_id, cursor_save_id, limit)
    )
    saves = query

    next_cursor = saves[-1].id if len(saves) == limit else None

    post_ids = [s.post_id for s in saves]
    if not post_ids:
        return SavedPostFeedResponse(posts=[], next_cursor=None)

    posts = repo.get_posts_by_ids(post_ids)
    post_map = {p.id: p for p in posts}
    ordered = [post_map[pid] for pid in post_ids if pid in post_map]
    return SavedPostFeedResponse(
        posts=batch_feed_cards(repo, ordered, profile_id),
        next_cursor=next_cursor,
    )
