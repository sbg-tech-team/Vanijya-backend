
import logging

from app.modules.post.data.models import CATEGORY_DEAL, Post, PostLike, PostComment, PostShare, PostSave, PostDealDetails
from app.modules.post.domain.interfaces.repository import IPostRepository
from app.modules.post.domain.exceptions import (
    PostNotFoundError, PostForbiddenError,
    CommentNotFoundError, CommentForbiddenError, CommentsDisabledError,
)
from app.modules.post.application.schemas import (
    PostDealResponse,
    CommentCreate, CommentResponse, CommentFeedResponse,
    LikeResponse, SaveResponse, ShareResponse, DealClosedResponse,
    PostSendRequest,
)
from app.modules.post.recommendation import service as rec_service
from app.modules.post.recommendation.constants import _ROLE_NAMES
from app.modules.post.recommendation.session_taste import service as interaction_service

import os

log = logging.getLogger(__name__)

_POST_STORAGE_BUCKET = os.environ.get("POST_STORAGE_BUCKET", "posts")


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _active_profile_ids(repo: IPostRepository) -> list[int]:
    return repo.active_profile_ids()


def _get_post_or_raise(repo: IPostRepository, post_id: int) -> Post:
    post = repo.get_active_post(post_id)
    if not post:
        raise PostNotFoundError(f"Post {post_id} not found")
    return post


def _profile_location(repo: IPostRepository, profile_id: int) -> tuple[float, float]:
    profile = repo.get_profile(profile_id)
    if not profile:
        return 0.0, 0.0
    return float(profile.business.latitude), float(profile.business.longitude)


# ----------------------------------------------------------------------------
# Likes
# ----------------------------------------------------------------------------

def toggle_like(repo: IPostRepository, post_id: int, profile_id: int) -> LikeResponse:
    post = _get_post_or_raise(repo, post_id)

    existing = repo.get_like(post_id, profile_id)

    if existing:
        repo.delete(existing)
        repo.bump_counter(post_id, "like_count", -1)
        repo.commit()
        repo.refresh(post)
        return LikeResponse(liked=False, like_count=post.like_count)
    else:
        repo.add(PostLike(post_id=post_id, profile_id=profile_id))
        repo.bump_counter(post_id, "like_count", 1)
        repo.commit()
        repo.refresh(post)
        try:
            interaction_service.record_interaction(repo.session, profile_id, post.category_id, "like", post.commodity_id, post.profile_id)
        except Exception:
            log.exception("taste update failed for like on post %s by profile %s", post_id, profile_id)
        return LikeResponse(liked=True, like_count=post.like_count)


# ----------------------------------------------------------------------------
# Comments
# ----------------------------------------------------------------------------

def add_comment(repo: IPostRepository, post_id: int, profile_id: int, payload: CommentCreate) -> CommentResponse:
    post = _get_post_or_raise(repo, post_id)

    if not post.allow_comments:
        raise CommentsDisabledError("Comments are disabled on this post")

    comment = PostComment(post_id=post_id, profile_id=profile_id, content=payload.content)
    repo.add(comment)
    repo.bump_counter(post_id, "comment_count", 1)
    repo.commit()
    repo.refresh(comment)

    try:
        interaction_service.record_interaction(repo.session, profile_id, post.category_id, "comment", post.commodity_id, post.profile_id)
    except Exception:
        log.exception("taste update failed for comment on post %s by profile %s", post_id, profile_id)

    commenter = repo.get_profile_with_business_by_id(profile_id)

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
    repo: IPostRepository,
    post_id: int,
    limit: int = 20,
    cursor_comment_id: int | None = None,
) -> CommentFeedResponse:
    _get_post_or_raise(repo, post_id)

    comments = repo.list_comments_asc(post_id, cursor_comment_id, limit)

    if not comments:
        return CommentFeedResponse(comments=[], next_cursor=None)

    commenter_ids = list({c.profile_id for c in comments})
    commenter_map = repo.get_commenters_with_business(commenter_ids)

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


def delete_comment(repo: IPostRepository, post_id: int, comment_id: int, profile_id: int) -> None:
    comment = repo.get_comment_on_post(post_id, comment_id)
    if not comment:
        raise CommentNotFoundError(f"Comment {comment_id} not found")
    if comment.profile_id != profile_id:
        raise CommentForbiddenError("You can only delete your own comments")
    repo.delete(comment)
    repo.bump_counter(post_id, "comment_count", -1)
    repo.commit()


# ----------------------------------------------------------------------------
# Shares
# ----------------------------------------------------------------------------

def record_share(repo: IPostRepository, post_id: int, profile_id: int) -> ShareResponse:
    """Increment share_count only — used for external shares (copy link, WhatsApp, etc.)."""
    post = _get_post_or_raise(repo, post_id)

    repo.add(PostShare(post_id=post_id, profile_id=profile_id))
    repo.bump_counter(post_id, "share_count", 1)
    repo.commit()
    repo.refresh(post)
    try:
        interaction_service.record_interaction(repo.session, profile_id, post.category_id, "share", post.commodity_id, post.profile_id)
    except Exception:
        log.exception("taste update failed for share on post %s by profile %s", post_id, profile_id)
    return ShareResponse(share_count=post.share_count)


def send_post(
    repo: IPostRepository,
    deliver_uc,
    post_id: int,
    profile_id: int,
    user_id: "UUID",
    payload: PostSendRequest,
) -> dict:
    """
    Full in-app share:
      1. Validate post exists.
      2. Deliver the post as a chat message to each selected DM / group.
         Chat owns the permission checks and silently skips recipients that
         fail them (partial delivery).
      3. Increment share_count once regardless of recipient count.
      4. Return share_count + raw delivery lists so the router can emit WebSocket events.
    """
    post = _get_post_or_raise(repo, post_id)

    dm_deliveries, group_deliveries = deliver_uc.execute(
        sender_id=user_id,
        message_type="post",
        dm_conversation_ids=payload.dm_conversation_ids,
        group_ids=payload.group_ids,
        caption=payload.caption,
        post_id=post_id,
    )

    repo.add(PostShare(post_id=post_id, profile_id=profile_id))
    repo.bump_counter(post_id, "share_count", 1)
    repo.commit()
    repo.refresh(post)
    try:
        interaction_service.record_interaction(repo.session, profile_id, post.category_id, "share", post.commodity_id, post.profile_id)
    except Exception:
        log.exception("taste update failed for share on post %s by profile %s", post_id, profile_id)

    return {
        "share_count": post.share_count,
        "dm_deliveries": dm_deliveries,
        "group_deliveries": group_deliveries,
    }


# ----------------------------------------------------------------------------
# Saves
# ----------------------------------------------------------------------------

def toggle_save(repo: IPostRepository, post_id: int, profile_id: int) -> SaveResponse:
    post = _get_post_or_raise(repo, post_id)

    existing = repo.get_save(post_id, profile_id)

    if existing:
        repo.delete(existing)
        repo.bump_counter(post_id, "save_count", -1)
        repo.commit()
        return SaveResponse(saved=False)
    else:
        repo.add(PostSave(post_id=post_id, profile_id=profile_id))
        repo.bump_counter(post_id, "save_count", 1)
        repo.commit()
        try:
            interaction_service.record_interaction(repo.session, profile_id, post.category_id, "save", post.commodity_id, post.profile_id)
        except Exception:
            log.exception("taste update failed for save on post %s by profile %s", post_id, profile_id)
        return SaveResponse(saved=True)


# ----------------------------------------------------------------------------
# Deal close / reopen
# ----------------------------------------------------------------------------

def toggle_deal_closed(repo: IPostRepository, post_id: int, profile_id: int) -> DealClosedResponse:
    post = _get_post_or_raise(repo, post_id)
    if post.profile_id != profile_id:
        raise PostForbiddenError("You can only close your own posts")
    if post.category_id != CATEGORY_DEAL:
        raise PostForbiddenError("Only Deal/Requirement posts can be closed")

    deal = post.deal_details
    if deal is None:
        raise PostForbiddenError("Deal details missing on this post")
    deal.is_closed = not deal.is_closed
    repo.commit()

    if deal.is_closed:
        try:
            rec_service.remove_post_index(repo, post_id)
            repo.commit()
        except Exception:
            repo.rollback()
            log.exception("de-indexing failed for closed deal on post %s", post_id)
    else:
        author_lat, author_lon = _profile_location(repo, post.profile_id)
        post_lat = float(post.latitude) if post.latitude is not None else author_lat
        post_lon = float(post.longitude) if post.longitude is not None else author_lon
        try:
            rec_service.index_post(
                repo=repo,
                post_id=post.id,
                commodity_id=post.commodity_id,
                target_role_ids=post.target_roles,
                lat=post_lat,
                lon=post_lon,
                category_id=post.category_id,
                commodity_quantity=float(deal.commodity_quantity),
            )
            repo.commit()
        except Exception:
            repo.rollback()
            log.exception("re-indexing failed for post %s — it will not surface in the feed", post_id)

    return DealClosedResponse(is_closed=deal.is_closed)
