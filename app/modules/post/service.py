import asyncio
import os
import uuid

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from datetime import datetime, timezone, timedelta

from app.modules.post.models import CATEGORY_DEAL, Post, PostDealDetails, PostView, PostLike, PostComment, PostShare, PostSave
from app.modules.profile.models import Profile
from app.modules.connections.models import UserConnection
from app.modules.post.schemas import (
    PostCreate, PostUpdate, PostResponse, PostDealResponse,
    CommentCreate, CommentResponse,
    LikeResponse, SaveResponse, ShareResponse, DealClosedResponse,
)
from app.modules.post.post_recommendation_module import service as rec_service
from app.modules.post.post_user_interaction import service as interaction_service
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
        .filter(Post.profile_id.in_(_active_profile_ids(db)))
        .order_by(Post.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return [_to_post_response(db, post, viewer_profile_id) for post in posts]


def get_my_posts(db: Session, profile_id: int, limit: int = 20, offset: int = 0) -> list[PostResponse]:
    posts = (
        db.query(Post)
        .filter(Post.profile_id == profile_id)
        .order_by(Post.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return [_to_post_response(db, post, profile_id) for post in posts]


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

    return CommentResponse(
        id=comment.id,
        post_id=comment.post_id,
        profile_id=comment.profile_id,
        content=comment.content,
        created_at=comment.created_at,
    )


def get_comments(db: Session, post_id: int, limit: int = 20, offset: int = 0) -> list[CommentResponse]:
    _get_post_or_raise(db, post_id)

    comments = (
        db.query(PostComment)
        .filter(PostComment.post_id == post_id)
        .order_by(PostComment.created_at.asc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return [
        CommentResponse(
            id=c.id,
            post_id=c.post_id,
            profile_id=c.profile_id,
            content=c.content,
            created_at=c.created_at,
        )
        for c in comments
    ]


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


def get_following_feed(db: Session, profile_id: int, limit: int = 20, offset: int = 0) -> list[PostResponse]:
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        return []

    following_user_ids = [
        row[0]
        for row in db.query(UserConnection.following_id)
        .filter(UserConnection.follower_id == profile.users_id)
        .all()
    ]
    if not following_user_ids:
        return []

    followed_profile_ids = [
        row[0]
        for row in db.query(Profile.id)
        .filter(Profile.users_id.in_(following_user_ids))
        .all()
    ]
    if not followed_profile_ids:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    posts = (
        db.query(Post)
        .filter(
            Post.profile_id.in_(followed_profile_ids),
            Post.created_at >= cutoff,
        )
        .order_by(Post.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return [_to_post_response(db, post, profile_id) for post in posts]


def get_saved_posts(db: Session, profile_id: int, limit: int = 20, offset: int = 0) -> list[PostResponse]:
    saves = (
        db.query(PostSave)
        .filter(PostSave.profile_id == profile_id)
        .order_by(PostSave.saved_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    post_ids = [s.post_id for s in saves]
    posts = (
        db.query(Post)
        .filter(
            Post.id.in_(post_ids),
            Post.profile_id.in_(_active_profile_ids(db)),
        )
        .all()
    )
    post_map = {p.id: p for p in posts}
    return [_to_post_response(db, post_map[pid], profile_id) for pid in post_ids if pid in post_map]
