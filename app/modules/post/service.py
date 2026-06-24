import asyncio
import math
import os
import uuid

from sqlalchemy.orm import Session, selectinload
from sqlalchemy.exc import IntegrityError

from datetime import datetime, timezone, timedelta

from app.modules.post.models import CATEGORY_DEAL, Post, PostDealDetails, PostView, PostLike, PostComment, PostShare, PostSave
from app.modules.profile.models import Profile
from app.modules.connections.models import UserConnection
from app.modules.post.schemas import (
    PostCreate, PostUpdate, PostResponse, PostDealResponse,
    FeedPostCard, MyPostCard, MyPostFeedResponse, PostFeedResponse, SavedPostFeedResponse, FollowingFeedResponse,
    CommentCreate, CommentResponse, CommentFeedResponse,
    LikeResponse, SaveResponse, ShareResponse, DealClosedResponse,
    PostSendRequest, PostSendResponse,
)
from app.modules.post.post_recommendation_module import service as rec_service
from app.modules.post.post_recommendation_module.models import SeenPost
from app.modules.post.post_recommendation_module.constants import FRESH_BOOST_PEAK, FRESH_DECAY_TAU
from app.modules.post.post_user_interaction import service as interaction_service
from app.modules.post.post_user_interaction.models import UserTasteProfile
from app.modules.post.post_user_interaction.constants import CATEGORY_NAMES, DEFAULT_TASTE
from app.shared.utils.storage import (
    ALLOWED_IMAGE_TYPES,
    StorageError,
    delete_object,
    ext_for,
    generate_signed_upload_url,
    object_exists,
    path_from_url,
    public_url,
)

_POST_STORAGE_BUCKET = os.environ.get("POST_STORAGE_BUCKET", "posts")


# ----------------------------------------------------------------------------
# Image upload
# ----------------------------------------------------------------------------

class PostImageUploadError(Exception):
    pass


class PostStorageUnavailableError(Exception):
    pass


async def get_post_upload_url(profile_id: int, content_type: str) -> dict:
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise PostImageUploadError(
            f"Unsupported type '{content_type}'. Allowed: image/jpeg, image/png, image/webp."
        )

    path = f"{profile_id}/{uuid.uuid4()}{ext_for(content_type)}"

    try:
        result = await generate_signed_upload_url(_POST_STORAGE_BUCKET, path)
    except StorageError as e:
        raise PostImageUploadError(str(e))

    return {
        **result,
        "image_url": public_url(_POST_STORAGE_BUCKET, path),
        "content_type": content_type,
    }


# ----------------------------------------------------------------------------
# Errors
# ----------------------------------------------------------------------------

class PostNotFoundError(Exception):
    pass


class PostForbiddenError(Exception):
    pass


class CommentNotFoundError(Exception):
    pass


class CommentForbiddenError(Exception):
    pass


class CommentsDisabledError(Exception):
    pass


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _active_profile_ids(db: Session) -> list[int]:
    return [row[0] for row in db.query(Profile.id).all()]


def _is_liked(db: Session, post_id: int, profile_id: int) -> bool:
    return db.query(PostLike).filter(
        PostLike.post_id == post_id,
        PostLike.profile_id == profile_id,
    ).first() is not None


def _is_saved(db: Session, post_id: int, profile_id: int) -> bool:
    return db.query(PostSave).filter(
        PostSave.post_id == post_id,
        PostSave.profile_id == profile_id,
    ).first() is not None


def _to_post_response(db: Session, post: Post, viewer_profile_id: int) -> PostResponse:
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
        is_liked=_is_liked(db, post.id, viewer_profile_id),
        is_saved=_is_saved(db, post.id, viewer_profile_id),
        view_count=post.view_count,
        like_count=post.like_count,
        comment_count=post.comment_count,
        share_count=post.share_count,
        save_count=post.save_count,
    )


def _batch_post_responses(
    db: Session,
    posts: list[Post],
    viewer_profile_id: int,
) -> list[PostResponse]:
    """Build PostResponse objects for a list of posts using batch DB lookups.

    Replaces per-post _is_liked / _is_saved calls with two single queries,
    eliminating the N+1 pattern in feed endpoints.
    """
    if not posts:
        return []

    post_ids = [p.id for p in posts]

    liked_ids = {
        row[0]
        for row in db.query(PostLike.post_id)
        .filter(PostLike.profile_id == viewer_profile_id, PostLike.post_id.in_(post_ids))
        .all()
    }
    saved_ids = {
        row[0]
        for row in db.query(PostSave.post_id)
        .filter(PostSave.profile_id == viewer_profile_id, PostSave.post_id.in_(post_ids))
        .all()
    }

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


_ROLE_NAMES = {1: "Trader", 2: "Broker", 3: "Exporter"}


def _batch_feed_cards(
    db: Session,
    posts: list[Post],
    viewer_profile_id: int,
    viewer_users_id=None,
) -> list[FeedPostCard]:
    """Build FeedPostCard objects with full author info and following status.

    viewer_users_id: pass when already available to save one query.
    """
    if not posts:
        return []

    post_ids = [p.id for p in posts]
    author_profile_ids = list({p.profile_id for p in posts})

    liked_ids = {
        row[0] for row in db.query(PostLike.post_id)
        .filter(PostLike.profile_id == viewer_profile_id, PostLike.post_id.in_(post_ids)).all()
    }
    saved_ids = {
        row[0] for row in db.query(PostSave.post_id)
        .filter(PostSave.profile_id == viewer_profile_id, PostSave.post_id.in_(post_ids)).all()
    }

    authors = {
        p.id: p
        for p in db.query(Profile)
        .options(selectinload(Profile.business))
        .filter(Profile.id.in_(author_profile_ids))
        .all()
    }

    if viewer_users_id is None:
        row = db.query(Profile.users_id).filter(Profile.id == viewer_profile_id).first()
        viewer_users_id = row[0] if row else None

    following_user_ids: set = set()
    if viewer_users_id:
        candidate_uids = [a.users_id for a in authors.values() if a.users_id]
        if candidate_uids:
            following_user_ids = {
                row[0] for row in db.query(UserConnection.following_id)
                .filter(
                    UserConnection.follower_id == viewer_users_id,
                    UserConnection.following_id.in_(candidate_uids),
                ).all()
            }

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
    db: Session,
    posts: list[Post],
    profile_id: int,
) -> list[MyPostCard]:
    """FeedPostCard fields + owner-only fields (created_at, is_public, etc.) for GET /posts/mine."""
    if not posts:
        return []

    post_ids = [p.id for p in posts]

    liked_ids = {
        row[0] for row in db.query(PostLike.post_id)
        .filter(PostLike.profile_id == profile_id, PostLike.post_id.in_(post_ids)).all()
    }
    saved_ids = {
        row[0] for row in db.query(PostSave.post_id)
        .filter(PostSave.profile_id == profile_id, PostSave.post_id.in_(post_ids)).all()
    }

    author = (
        db.query(Profile)
        .options(selectinload(Profile.business))
        .filter(Profile.id == profile_id)
        .first()
    )
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


def _following_taste_counts(taste: UserTasteProfile | None, role_id: int) -> dict[str, int]:
    if taste and taste.total_events > 0:
        return {
            "market_update": taste.market_update_count,
            "deal_req":      taste.deal_req_count,
            "discussion":    taste.discussion_count,
            "knowledge":     taste.knowledge_count,
        }
    return DEFAULT_TASTE.get(role_id, DEFAULT_TASTE[1])


def _score_following_posts(
    posts: list[Post],
    viewer_commodity_ids: set[int],
    taste_counts: dict[str, int],
) -> list[tuple[Post, float]]:
    now = datetime.now(timezone.utc)
    total_taste = sum(math.log1p(v) for v in taste_counts.values()) or 1.0
    results = []
    for post in posts:
        commodity_boost = 1.3 if post.commodity_id in viewer_commodity_ids else 1.0

        cat_key = CATEGORY_NAMES.get(post.category_id, "")
        cat_w = math.log1p(taste_counts.get(cat_key, 0)) / total_taste

        created_at = post.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age_h = max(0.0, (now - created_at).total_seconds() / 3600)
        freshness = 1.0 + FRESH_BOOST_PEAK * math.exp(-age_h / FRESH_DECAY_TAU)

        # Closed deals are shown but ranked lower
        closed_penalty = 0.5 if (post.deal_details and post.deal_details.is_closed) else 1.0

        engagement = math.log1p(post.like_count * 2 + post.save_count * 3 + post.comment_count)
        score = (0.5 + cat_w) * commodity_boost * freshness * closed_penalty * (1.0 + 0.05 * engagement)
        results.append((post, score))
    return results


def _get_post_or_raise(db: Session, post_id: int) -> Post:
    post = (
        db.query(Post)
        .filter(
            Post.id == post_id,
            Post.profile_id.in_(_active_profile_ids(db)),
        )
        .first()
    )
    if not post:
        raise PostNotFoundError(f"Post {post_id} not found")
    return post


def _profile_location(db: Session, profile_id: int) -> tuple[float, float]:
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        return 0.0, 0.0
    return float(profile.business.latitude), float(profile.business.longitude)


# ----------------------------------------------------------------------------
# Post CRUD
# ----------------------------------------------------------------------------

async def _verify_image_urls(profile_id: int, urls: list[str]) -> None:
    """Verify each URL belongs to this profile and exists in storage."""
    for url in urls:
        try:
            path = path_from_url(_POST_STORAGE_BUCKET, url)
        except StorageError:
            raise PostImageUploadError(f"image_url does not belong to the posts storage bucket: {url}")

        parts = path.strip("/").split("/")
        if len(parts) < 2:
            raise PostImageUploadError(f"Invalid storage path for: {url}")
        if parts[0] != str(profile_id):
            raise PostImageUploadError("Image does not belong to this profile")

        result = None
        for delay in (0.15, 0.35):
            result = await object_exists(_POST_STORAGE_BUCKET, path)
            if result is True or result is None:
                break
            await asyncio.sleep(delay)
        else:
            result = await object_exists(_POST_STORAGE_BUCKET, path)

        if result is None:
            raise PostStorageUnavailableError("Storage verification temporarily unavailable")
        if result is not True:
            raise PostImageUploadError(
                f"Image not found in storage — complete the upload before creating a post: {url}"
            )


async def create_post(db: Session, profile_id: int, payload: PostCreate) -> PostResponse:
    if payload.image_urls:
        await _verify_image_urls(profile_id, payload.image_urls)

    post = Post(
        profile_id=profile_id,
        category_id=payload.category_id,
        commodity_id=payload.commodity_id,
        title=payload.title,
        caption=payload.caption,
        image_urls=payload.image_urls,
        is_public=payload.is_public,
        target_roles=payload.target_roles,
        allow_comments=payload.allow_comments,
    )
    db.add(post)
    db.commit()
    db.refresh(post)

    deal = None
    if payload.category_id == CATEGORY_DEAL and payload.deal_details:
        deal = PostDealDetails(post_id=post.id, **payload.deal_details.model_dump())
        db.add(deal)
        db.commit()
        db.refresh(post)

    author_lat, author_lon = _profile_location(db, profile_id)
    post_lat = float(post.latitude) if post.latitude is not None else author_lat
    post_lon = float(post.longitude) if post.longitude is not None else author_lon
    try:
        rec_service.index_post(
            db=db,
            post_id=post.id,
            commodity_id=post.commodity_id,
            target_role_ids=post.target_roles,
            lat=post_lat,
            lon=post_lon,
            category_id=post.category_id,
            commodity_quantity=float(deal.commodity_quantity) if deal else None,
        )
    except Exception:
        pass  # embedding failure must never break post creation

    return _to_post_response(db, post, profile_id)


def get_post(db: Session, post_id: int, viewer_profile_id: int) -> PostResponse:
    post = _get_post_or_raise(db, post_id)
    _record_view(db, post_id, viewer_profile_id)
    db.refresh(post)
    try:
        rec_service.record_seen(db, viewer_profile_id, [post_id])
    except Exception:
        pass
    return _to_post_response(db, post, viewer_profile_id)


def update_post(db: Session, post_id: int, profile_id: int, payload: PostUpdate) -> PostResponse:
    post = _get_post_or_raise(db, post_id)
    if post.profile_id != profile_id:
        raise PostForbiddenError("You can only edit your own posts")

    top_level = payload.model_dump(exclude_none=True, exclude={"deal_details"})
    for field, value in top_level.items():
        setattr(post, field, value)

    if payload.deal_details and post.deal_details:
        for field, value in payload.deal_details.model_dump(exclude_none=True).items():
            setattr(post.deal_details, field, value)

    db.commit()
    db.refresh(post)
    return _to_post_response(db, post, profile_id)


async def delete_post(db: Session, post_id: int, profile_id: int) -> None:
    post = _get_post_or_raise(db, post_id)
    if post.profile_id != profile_id:
        raise PostForbiddenError("You can only delete your own posts")

    image_urls = post.image_urls or []

    try:
        rec_service.remove_post_index(db, post_id)
    except Exception:
        pass

    db.delete(post)
    db.commit()

    for url in image_urls:
        try:
            old_path = path_from_url(_POST_STORAGE_BUCKET, url)
            await delete_object(_POST_STORAGE_BUCKET, old_path)
        except StorageError:
            pass


def get_feed(db: Session, viewer_profile_id: int, limit: int = 20, offset: int = 0) -> list[PostResponse]:
    posts = (
        db.query(Post)
        .options(selectinload(Post.deal_details))
        .filter(Post.profile_id.in_(_active_profile_ids(db)))
        .order_by(Post.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return _batch_post_responses(db, posts, viewer_profile_id)


def get_my_posts(
    db: Session,
    profile_id: int,
    limit: int = 20,
    cursor_post_id: int | None = None,
) -> MyPostFeedResponse:
    query = (
        db.query(Post)
        .options(selectinload(Post.deal_details))
        .filter(Post.profile_id == profile_id)
    )
    if cursor_post_id is not None:
        query = query.filter(Post.id < cursor_post_id)
    posts = query.order_by(Post.id.desc()).limit(limit).all()
    next_cursor = posts[-1].id if len(posts) == limit else None
    return MyPostFeedResponse(
        posts=_batch_my_post_cards(db, posts, profile_id),
        next_cursor=next_cursor,
    )


# ----------------------------------------------------------------------------
# Views
# ----------------------------------------------------------------------------

def _record_view(db: Session, post_id: int, profile_id: int) -> None:
    view = PostView(post_id=post_id, profile_id=profile_id)
    db.add(view)
    try:
        db.flush()
        db.query(Post).filter(Post.id == post_id).update(
            {Post.view_count: Post.view_count + 1},
            synchronize_session=False,
        )
        db.commit()
    except IntegrityError:
        db.rollback()  # duplicate view — log as revisit instead of incrementing
        interaction_service.record_revisit_event(db, profile_id, post_id)


# ----------------------------------------------------------------------------
# Likes
# ----------------------------------------------------------------------------

def toggle_like(db: Session, post_id: int, profile_id: int) -> LikeResponse:
    post = _get_post_or_raise(db, post_id)

    existing = db.query(PostLike).filter(
        PostLike.post_id == post_id,
        PostLike.profile_id == profile_id,
    ).first()

    if existing:
        db.delete(existing)
        db.query(Post).filter(Post.id == post_id).update(
            {Post.like_count: Post.like_count - 1},
            synchronize_session=False,
        )
        db.commit()
        db.refresh(post)
        return LikeResponse(liked=False, like_count=post.like_count)
    else:
        db.add(PostLike(post_id=post_id, profile_id=profile_id))
        db.query(Post).filter(Post.id == post_id).update(
            {Post.like_count: Post.like_count + 1},
            synchronize_session=False,
        )
        db.commit()
        db.refresh(post)
        try:
            interaction_service.record_interaction(db, profile_id, post.category_id, "like", post.commodity_id, post.profile_id)
        except Exception:
            pass
        return LikeResponse(liked=True, like_count=post.like_count)


# ----------------------------------------------------------------------------
# Comments
# ----------------------------------------------------------------------------

def add_comment(db: Session, post_id: int, profile_id: int, payload: CommentCreate) -> CommentResponse:
    post = _get_post_or_raise(db, post_id)

    if not post.allow_comments:
        raise CommentsDisabledError("Comments are disabled on this post")

    comment = PostComment(post_id=post_id, profile_id=profile_id, content=payload.content)
    db.add(comment)
    db.query(Post).filter(Post.id == post_id).update(
        {Post.comment_count: Post.comment_count + 1},
        synchronize_session=False,
    )
    db.commit()
    db.refresh(comment)

    try:
        interaction_service.record_interaction(db, profile_id, post.category_id, "comment", post.commodity_id, post.profile_id)
    except Exception:
        pass

    commenter = db.query(Profile).options(selectinload(Profile.business)).filter(Profile.id == profile_id).first()

    return CommentResponse(
        id=comment.id,
        post_id=comment.post_id,
        content=comment.content,
        commenter_profile_id=comment.profile_id,
        commenter_user_id=str(commenter.users_id) if commenter else "",
        commenter_name=commenter.name if commenter else "",
        commenter_role=_ROLE_NAMES.get(commenter.role_id, "Trader") if commenter else "Trader",
        commenter_company=commenter.business.business_name if commenter and commenter.business else None,
        commenter_avatar_url=commenter.avatar_url if commenter else None,
        is_user_verified=commenter.is_user_verified if commenter else False,
        is_business_verified=commenter.is_business_verified if commenter else False,
        created_at=comment.created_at,
    )


def get_comments(
    db: Session,
    post_id: int,
    limit: int = 20,
    cursor_comment_id: int | None = None,
) -> CommentFeedResponse:
    _get_post_or_raise(db, post_id)

    query = db.query(PostComment).filter(PostComment.post_id == post_id)
    if cursor_comment_id is not None:
        query = query.filter(PostComment.id > cursor_comment_id)
    comments = query.order_by(PostComment.id.asc()).limit(limit).all()

    if not comments:
        return CommentFeedResponse(comments=[], next_cursor=None)

    commenter_ids = list({c.profile_id for c in comments})
    commenter_map = {
        p.id: p
        for p in db.query(Profile)
        .options(selectinload(Profile.business))
        .filter(Profile.id.in_(commenter_ids))
        .all()
    }

    responses = []
    for c in comments:
        commenter = commenter_map.get(c.profile_id)
        biz = commenter.business if commenter else None
        responses.append(CommentResponse(
            id=c.id,
            post_id=c.post_id,
            content=c.content,
            commenter_profile_id=c.profile_id,
            commenter_user_id=str(commenter.users_id) if commenter else "",
            commenter_name=commenter.name if commenter else "",
            commenter_role=_ROLE_NAMES.get(commenter.role_id, "Trader") if commenter else "Trader",
            commenter_company=biz.business_name if biz else None,
            commenter_avatar_url=commenter.avatar_url if commenter else None,
            is_user_verified=commenter.is_user_verified if commenter else False,
            is_business_verified=commenter.is_business_verified if commenter else False,
            created_at=c.created_at,
        ))

    next_cursor = comments[-1].id if len(comments) == limit else None
    return CommentFeedResponse(comments=responses, next_cursor=next_cursor)


def delete_comment(db: Session, post_id: int, comment_id: int, profile_id: int) -> None:
    comment = db.query(PostComment).filter(
        PostComment.id == comment_id,
        PostComment.post_id == post_id,
    ).first()
    if not comment:
        raise CommentNotFoundError(f"Comment {comment_id} not found")
    if comment.profile_id != profile_id:
        raise CommentForbiddenError("You can only delete your own comments")
    db.delete(comment)
    db.query(Post).filter(Post.id == post_id).update(
        {Post.comment_count: Post.comment_count - 1},
        synchronize_session=False,
    )
    db.commit()


# ----------------------------------------------------------------------------
# Shares
# ----------------------------------------------------------------------------

def record_share(db: Session, post_id: int, profile_id: int) -> ShareResponse:
    """Increment share_count only — used for external shares (copy link, WhatsApp, etc.)."""
    post = _get_post_or_raise(db, post_id)

    db.add(PostShare(post_id=post_id, profile_id=profile_id))
    db.query(Post).filter(Post.id == post_id).update(
        {Post.share_count: Post.share_count + 1},
        synchronize_session=False,
    )
    db.commit()
    db.refresh(post)
    try:
        interaction_service.record_interaction(db, profile_id, post.category_id, "share", post.commodity_id, post.profile_id)
    except Exception:
        pass
    return ShareResponse(share_count=post.share_count)


def send_post(
    db: Session,
    post_id: int,
    profile_id: int,
    user_id: "UUID",
    payload: PostSendRequest,
) -> dict:
    """
    Full in-app share:
      1. Validate post exists.
      2. Deliver the post as a chat message to each selected DM / group.
         Silently skips recipients that fail permission checks (partial delivery).
      3. Increment share_count once regardless of recipient count.
      4. Return share_count + raw delivery lists so the router can emit WebSocket events.
    """
    from uuid import UUID as _UUID
    from app.modules.chat.data.repository import ChatRepository
    from app.modules.chat.domain.entities import ConvStatus

    post = _get_post_or_raise(db, post_id)
    chat_repo = ChatRepository(db)

    dm_deliveries: list[tuple] = []
    for conv_id in payload.dm_conversation_ids:
        guard = chat_repo.get_conv_send_info(conv_id, user_id)
        if guard:  # and guard.status == ConvStatus.ACTIVE:
            msg = chat_repo.save_message(
                context_type="dm",
                context_id=conv_id,
                sender_id=user_id,
                message_type="post",
                post_id=post_id,
                body=payload.caption,
            )
            dm_deliveries.append((guard.receiver_id, msg))

    group_deliveries: list[tuple] = []
    for group_id in payload.group_ids:
        chat_perm = chat_repo.get_group_chat_perm(group_id)
        member_role = chat_repo.get_group_member_role(group_id, user_id)
        is_frozen = chat_repo.is_group_member_frozen(group_id, user_id)
        if (chat_perm and member_role and not is_frozen
                and (chat_perm == "all_members" or member_role == "admin")):
            msg = chat_repo.save_message(
                context_type="group",
                context_id=group_id,
                sender_id=user_id,
                message_type="post",
                post_id=post_id,
                body=payload.caption,
            )
            group_deliveries.append((group_id, msg))

    db.add(PostShare(post_id=post_id, profile_id=profile_id))
    db.query(Post).filter(Post.id == post_id).update(
        {Post.share_count: Post.share_count + 1},
        synchronize_session=False,
    )
    db.commit()
    db.refresh(post)
    try:
        interaction_service.record_interaction(db, profile_id, post.category_id, "share", post.commodity_id, post.profile_id)
    except Exception:
        pass

    return {
        "share_count": post.share_count,
        "dm_deliveries": dm_deliveries,
        "group_deliveries": group_deliveries,
    }


# ----------------------------------------------------------------------------
# Saves
# ----------------------------------------------------------------------------

def toggle_save(db: Session, post_id: int, profile_id: int) -> SaveResponse:
    post = _get_post_or_raise(db, post_id)

    existing = db.query(PostSave).filter(
        PostSave.post_id == post_id,
        PostSave.profile_id == profile_id,
    ).first()

    if existing:
        db.delete(existing)
        db.query(Post).filter(Post.id == post_id).update(
            {Post.save_count: Post.save_count - 1},
            synchronize_session=False,
        )
        db.commit()
        return SaveResponse(saved=False)
    else:
        db.add(PostSave(post_id=post_id, profile_id=profile_id))
        db.query(Post).filter(Post.id == post_id).update(
            {Post.save_count: Post.save_count + 1},
            synchronize_session=False,
        )
        db.commit()
        try:
            interaction_service.record_interaction(db, profile_id, post.category_id, "save", post.commodity_id, post.profile_id)
        except Exception:
            pass
        return SaveResponse(saved=True)


# ----------------------------------------------------------------------------
# Deal close / reopen
# ----------------------------------------------------------------------------

def toggle_deal_closed(db: Session, post_id: int, profile_id: int) -> DealClosedResponse:
    post = _get_post_or_raise(db, post_id)
    if post.profile_id != profile_id:
        raise PostForbiddenError("You can only close your own posts")
    if post.category_id != CATEGORY_DEAL:
        raise PostForbiddenError("Only Deal/Requirement posts can be closed")

    deal = post.deal_details
    if deal is None:
        raise PostForbiddenError("Deal details missing on this post")
    deal.is_closed = not deal.is_closed
    db.commit()

    if deal.is_closed:
        try:
            rec_service.remove_post_index(db, post_id)
        except Exception:
            pass
    else:
        author_lat, author_lon = _profile_location(db, post.profile_id)
        post_lat = float(post.latitude) if post.latitude is not None else author_lat
        post_lon = float(post.longitude) if post.longitude is not None else author_lon
        try:
            rec_service.index_post(
                db=db,
                post_id=post.id,
                commodity_id=post.commodity_id,
                target_role_ids=post.target_roles,
                lat=post_lat,
                lon=post_lon,
                category_id=post.category_id,
                commodity_quantity=float(deal.commodity_quantity),
            )
        except Exception:
            pass

    return DealClosedResponse(is_closed=deal.is_closed)


def get_following_feed(
    db: Session,
    profile_id: int,
    limit: int = 20,
    cursor_post_id: int | None = None,
) -> FollowingFeedResponse:
    profile = (
        db.query(Profile)
        .options(selectinload(Profile.commodities))
        .filter(Profile.id == profile_id)
        .first()
    )
    if not profile:
        return FollowingFeedResponse(posts=[], all_caught_up=False)

    # Single join query: follower → user_connections → profile
    followed_profile_ids = [
        row[0]
        for row in db.query(Profile.id)
        .join(UserConnection, UserConnection.following_id == Profile.users_id)
        .filter(UserConnection.follower_id == profile.users_id)
        .all()
    ]
    if not followed_profile_ids:
        return FollowingFeedResponse(posts=[], all_caught_up=False)

    # Posts already seen (shared with recommendation feed)
    seen_ids: set[int] = {
        row[0]
        for row in db.query(SeenPost.post_id)
        .filter(SeenPost.profile_id == profile_id)
        .all()
    }

    # Fetch unseen candidate posts from the last 30 days
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    query = (
        db.query(Post)
        .options(selectinload(Post.deal_details))
        .filter(
            Post.profile_id.in_(followed_profile_ids),
            Post.created_at >= cutoff,
        )
    )
    if seen_ids:
        query = query.filter(Post.id.notin_(seen_ids))
    posts = query.all()

    # "All caught up" — no unseen posts from last 3 days, but some exist (seen or not)
    three_day_cutoff = datetime.now(timezone.utc) - timedelta(days=3)
    recent_unseen = [
        p for p in posts
        if (p.created_at if p.created_at.tzinfo else p.created_at.replace(tzinfo=timezone.utc))
        >= three_day_cutoff
    ]
    all_caught_up = False
    if not recent_unseen and seen_ids:
        all_caught_up = db.query(Post.id).filter(
            Post.profile_id.in_(followed_profile_ids),
            Post.created_at >= three_day_cutoff,
            Post.id.in_(seen_ids),
        ).first() is not None

    # Score and rank
    taste = db.query(UserTasteProfile).filter(UserTasteProfile.profile_id == profile_id).first()
    taste_counts = _following_taste_counts(taste, profile.role_id)
    viewer_commodity_ids = {pc.commodity_id for pc in profile.commodities}
    scored = _score_following_posts(posts, viewer_commodity_ids, taste_counts)
    scored.sort(key=lambda x: x[1], reverse=True)

    # Cursor pagination
    start = 0
    if cursor_post_id is not None:
        ranked_ids = [p.id for p, _ in scored]
        try:
            start = ranked_ids.index(cursor_post_id) + 1
        except ValueError:
            start = 0  # cursor post was seen/removed; restart from top

    page_posts = [p for p, _ in scored[start: start + limit]]
    next_cursor = page_posts[-1].id if len(page_posts) == limit else None

    return FollowingFeedResponse(
        posts=_batch_feed_cards(db, page_posts, profile_id, viewer_users_id=profile.users_id),
        all_caught_up=all_caught_up,
        next_cursor=next_cursor,
    )


def get_saved_posts(
    db: Session,
    profile_id: int,
    limit: int = 20,
    cursor_save_id: int | None = None,
) -> SavedPostFeedResponse:
    query = (
        db.query(PostSave)
        .filter(PostSave.profile_id == profile_id)
    )
    if cursor_save_id is not None:
        query = query.filter(PostSave.id < cursor_save_id)
    saves = query.order_by(PostSave.id.desc()).limit(limit).all()

    next_cursor = saves[-1].id if len(saves) == limit else None

    post_ids = [s.post_id for s in saves]
    if not post_ids:
        return SavedPostFeedResponse(posts=[], next_cursor=None)

    posts = (
        db.query(Post)
        .options(selectinload(Post.deal_details))
        .filter(Post.id.in_(post_ids))
        .all()
    )
    post_map = {p.id: p for p in posts}
    ordered = [post_map[pid] for pid in post_ids if pid in post_map]
    return SavedPostFeedResponse(
        posts=_batch_feed_cards(db, ordered, profile_id),
        next_cursor=next_cursor,
    )
