import asyncio
import os
import uuid

from sqlalchemy.orm import Session

from app.modules.post.data.models import CATEGORY_DEAL, Post, PostDealDetails
from app.modules.post.domain.interfaces.repository import IPostRepository
from app.modules.post.domain.exceptions import PostImageUploadError, PostStorageUnavailableError
from app.modules.post.application.schemas import PostCreate, PostResponse, PostDealResponse
from app.modules.profile.data.models import Profile
from app.modules.post.recommendation import service as rec_service
from app.modules.post.recommendation.constants import _ROLE_NAMES
from app.shared.utils.storage import (
    ALLOWED_IMAGE_TYPES,
    StorageError,
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


def _profile_location(repo: IPostRepository, profile_id: int) -> tuple[float, float]:
    profile = repo.get_profile(profile_id)
    if not profile:
        return 0.0, 0.0
    return float(profile.business.latitude), float(profile.business.longitude)


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


# ----------------------------------------------------------------------------
# Create post
# ----------------------------------------------------------------------------

async def create_post(repo: IPostRepository, profile_id: int, payload: PostCreate) -> PostResponse:
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
    repo.add(post)
    repo.commit()
    repo.refresh(post)

    deal = None
    if payload.category_id == CATEGORY_DEAL and payload.deal_details:
        deal = PostDealDetails(post_id=post.id, **payload.deal_details.model_dump())
        repo.add(deal)
        repo.commit()
        repo.refresh(post)

    author_lat, author_lon = _profile_location(repo, profile_id)
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
            commodity_quantity=float(deal.commodity_quantity) if deal else None,
        )
    except Exception:
        pass  # embedding failure must never break post creation

    return _to_post_response(repo, post, profile_id)
