from sqlalchemy.orm import Session

from app.modules.post.data.models import Post
from app.modules.post.domain.interfaces.repository import IPostRepository
from app.modules.post.domain.exceptions import PostNotFoundError, PostForbiddenError
from app.modules.post.application.schemas import PostUpdate, PostResponse, PostDealResponse
from app.modules.profile.data.models import Profile


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _active_profile_ids(repo: IPostRepository) -> list[int]:
    return repo.active_profile_ids()


def _is_liked(repo, post_id, profile_id):
    from app.modules.post.data.models import PostLike
    return repo.is_liked(post_id, profile_id)


def _is_saved(repo, post_id, profile_id):
    from app.modules.post.data.models import PostSave
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


def _get_post_or_raise(repo: IPostRepository, post_id: int) -> Post:
    post = repo.get_active_post(post_id)
    if not post:
        raise PostNotFoundError(f"Post {post_id} not found")
    return post


# ----------------------------------------------------------------------------
# Update post
# ----------------------------------------------------------------------------

def update_post(repo: IPostRepository, post_id: int, profile_id: int, payload: PostUpdate) -> PostResponse:
    post = _get_post_or_raise(repo, post_id)
    if post.profile_id != profile_id:
        raise PostForbiddenError("You can only edit your own posts")

    top_level = payload.model_dump(exclude_none=True, exclude={"deal_details"})
    for field, value in top_level.items():
        setattr(post, field, value)

    if payload.deal_details and post.deal_details:
        for field, value in payload.deal_details.model_dump(exclude_none=True).items():
            setattr(post.deal_details, field, value)

    repo.commit()
    repo.refresh(post)
    return _to_post_response(repo, post, profile_id)
