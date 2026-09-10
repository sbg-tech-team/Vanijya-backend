"""
Group media and deals use cases — upload, list, delete media; create, list,
get, update, close, and publish deals.

All functions are pure business logic; no FastAPI imports.
Domain exceptions from app.modules.groups.domain.exceptions are raised on error.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.profile.data.models import Profile
from app.modules.groups.data.models import (
    GroupDeal,
    GroupMedia,
)
from app.modules.groups.application.schemas import (
    GroupDealCreate,
    GroupDealListOut,
    GroupDealResponse,
    GroupDealUpdate,
    GroupMediaOut,
    GroupMediaUploadOut,
)
from app.modules.groups.domain.interfaces.repository import IGroupsRepository
from app.modules.groups.domain.exceptions import (
    GroupDealAlreadyPublishedError,
    GroupDealEditForbiddenError,
    GroupMediaDeleteForbiddenError,
    GroupMediaNotFoundError,
    GroupMemberFrozenError,
    GroupNotFoundError,
    GroupPermissionError,
    GroupProfileNotFoundError,
    GroupStorageError,
    GroupValidationError,
)
from app.shared.utils.storage import (
    ALLOWED_IMAGE_TYPES,
    StorageError,
    delete_object,
    ext_for,
    generate_signed_upload_url,
    public_url,
)

# Re-import shared helpers from create_group to avoid duplication
from app.modules.groups.application.use_cases.create_group import (
    _get_group_or_raise,
    _get_membership,
    _require_member,
)

_GROUP_MEDIA_BUCKET = os.environ.get("GROUP_MEDIA_BUCKET", "group-media")

ALLOWED_MEDIA_TYPES = ALLOWED_IMAGE_TYPES | frozenset({
    "video/mp4",
    "video/quicktime",
    "video/webm",
})

_MEDIA_TYPE_EXT = {
    "video/mp4":       ".mp4",
    "video/quicktime": ".mov",
    "video/webm":      ".webm",
}

_MEDIA_CATEGORY = {
    **{t: "image" for t in ALLOWED_IMAGE_TYPES},
    "video/mp4": "video",
    "video/quicktime": "video",
    "video/webm": "video",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _deal_to_response(deal: GroupDeal) -> GroupDealResponse:
    return GroupDealResponse(
        id=deal.id,
        group_id=deal.group_id,
        posted_by=deal.posted_by,
        commodity_id=deal.commodity_id,
        title=deal.title,
        caption=deal.caption,
        grain_type=deal.grain_type,
        grain_size=deal.grain_size,
        commodity_quantity=float(deal.commodity_quantity),
        quantity_unit=deal.quantity_unit,
        commodity_price=float(deal.commodity_price),
        price_type=deal.price_type,
        image_urls=deal.image_urls,
        is_closed=deal.is_closed,
        post_id=deal.post_id,
        created_at=deal.created_at,
        updated_at=deal.updated_at,
    )


def _create_post_from_deal(repo: IGroupsRepository, deal: GroupDeal, profile_id: int, is_public: bool):
    """Insert a Post + PostDealDetails snapshot and index it for the rec engine."""
    from app.modules.post.data.models import Post, PostDealDetails, CATEGORY_DEAL
    from app.modules.post.recommendation import service as rec_service
    from app.modules.profile.data.models import Profile

    post = Post(
        profile_id=profile_id,
        category_id=CATEGORY_DEAL,
        commodity_id=deal.commodity_id,
        title=deal.title,
        caption=deal.caption,
        is_public=is_public,
    )
    repo.add(post)
    repo.flush()  # get post.id

    details = PostDealDetails(
        post_id=post.id,
        grain_type=deal.grain_type,
        grain_size=deal.grain_size,
        commodity_quantity=float(deal.commodity_quantity),
        quantity_unit=deal.quantity_unit,
        commodity_price=float(deal.commodity_price),
        price_type=deal.price_type,
        is_closed=deal.is_closed,
    )
    repo.add(details)
    repo.flush()

    # resolve location for rec vector
    profile = repo.get_profile_by_id(profile_id)
    lat, lon = 0.0, 0.0
    if profile and profile.business:
        lat = float(profile.business.latitude or 0.0)
        lon = float(profile.business.longitude or 0.0)

    try:
        rec_service.index_post(
            repo=repo,
            post_id=post.id,
            commodity_id=post.commodity_id,
            target_role_ids=None,
            lat=lat,
            lon=lon,
            category_id=CATEGORY_DEAL,
            commodity_quantity=float(deal.commodity_quantity),
        )
    except Exception:
        pass  # embedding failure must never break deal publishing

    return post


def _insert_deal_chat_card(repo: IGroupsRepository, deal: GroupDeal) -> None:
    """Drop a system card into the group chat so members see the new deal."""
    from app.modules.chat.data.models import Message
    msg = Message(
        context_type="group",
        context_id=deal.group_id,
        sender_id=deal.posted_by,
        message_type="deal",
        deal_id=deal.id,
        media_metadata={
            "title": deal.title,
            "commodity_id": deal.commodity_id,
        },
    )
    repo.add(msg)


# ---------------------------------------------------------------------------
# Group media upload (group-media bucket)
# ---------------------------------------------------------------------------

async def get_group_media_upload_url(
    repo: IGroupsRepository,
    group_id: UUID,
    user_id: UUID,
    content_type: str,
) -> GroupMediaUploadOut:
    """
    Creates a GroupMedia DB record and returns a signed upload URL.
    Supported: image/jpeg, image/png, image/webp, video/mp4, video/quicktime, video/webm.
    Only group members can upload media.
    """
    if content_type not in ALLOWED_MEDIA_TYPES:
        raise GroupValidationError(
            f"Unsupported type '{content_type}'. "
            "Allowed: image/jpeg, image/png, image/webp, video/mp4, video/quicktime, video/webm."
        )

    _require_member(repo, group_id, user_id)
    _get_group_or_raise(repo, group_id)

    ext = _MEDIA_TYPE_EXT.get(content_type) or ext_for(content_type)
    media_id = uuid.uuid4()
    path = f"{group_id}/{media_id}{ext}"
    media_category = _MEDIA_CATEGORY[content_type]

    try:
        result = await generate_signed_upload_url(_GROUP_MEDIA_BUCKET, path)
    except StorageError as e:
        raise GroupStorageError(str(e))

    media_url = public_url(_GROUP_MEDIA_BUCKET, path)

    record = GroupMedia(
        id=media_id,
        group_id=group_id,
        uploaded_by=user_id,
        media_url=media_url,
        media_type=media_category,
        storage_path=path,
    )
    repo.add(record)
    repo.commit()

    return GroupMediaUploadOut(
        media_id=media_id,
        upload_url=result["upload_url"],
        media_url=media_url,
        media_type=media_category,
        expires_at=result["expires_at"],
    )


def list_group_media(
    repo: IGroupsRepository,
    group_id: UUID,
    user_id: UUID,
    page: int = 1,
    limit: int = 20,
) -> dict:
    _get_group_or_raise(repo, group_id)
    _require_member(repo, group_id, user_id)

    total = repo.count_media(group_id)
    items = repo.list_media(group_id, page, limit)

    return {
        "media": [GroupMediaOut.model_validate(m) for m in items],
        "total": total,
        "page": page,
        "limit": limit,
    }


async def delete_group_media(
    repo: IGroupsRepository,
    group_id: UUID,
    media_id: UUID,
    user_id: UUID,
) -> None:
    """Admin or the uploader can delete a media item."""
    _get_group_or_raise(repo, group_id)

    record = (
        repo.get_media(group_id, media_id)
    )
    if not record:
        raise GroupMediaNotFoundError("Media not found")

    membership = _get_membership(repo, group_id, user_id)
    is_admin = membership and membership.role == "admin"
    is_uploader = record.uploaded_by == user_id

    if not (is_admin or is_uploader):
        raise GroupMediaDeleteForbiddenError("Only admins or the uploader can delete media")

    try:
        await delete_object(_GROUP_MEDIA_BUCKET, record.storage_path)
    except StorageError:
        pass  # best-effort — remove DB record regardless

    repo.delete(record)
    repo.commit()


# ---------------------------------------------------------------------------
# Group Deals
# ---------------------------------------------------------------------------

def create_group_deal(
    repo: IGroupsRepository,
    group_id: UUID,
    user_id: UUID,
    payload: GroupDealCreate,
) -> GroupDealResponse:
    group = _get_group_or_raise(repo, group_id)
    member = _get_membership(repo, group_id, user_id)
    if not member:
        raise GroupPermissionError("Must be a group member to post deals")
    if group.posting_perm == "admins_only" and member.role != "admin":
        raise GroupPermissionError("Only admins can post deals in this group")
    if member.is_frozen:
        raise GroupMemberFrozenError("Your posting access has been frozen by an admin")

    try:
        deal = GroupDeal(
            group_id=group_id,
            posted_by=user_id,
            commodity_id=payload.commodity_id,
            title=payload.title.strip(),
            caption=payload.caption.strip(),
            grain_type=payload.grain_type,
            grain_size=payload.grain_size,
            commodity_quantity=payload.commodity_quantity,
            quantity_unit=payload.quantity_unit,
            commodity_price=payload.commodity_price,
            price_type=payload.price_type,
            image_urls=payload.image_urls,
        )
        repo.add(deal)
        repo.flush()

        _insert_deal_chat_card(repo, deal)

        if payload.publish_to_feed:
            profile = repo.get_profile_by_user(user_id)
            if profile is None:
                raise GroupProfileNotFoundError("Profile not found")
            post = _create_post_from_deal(repo, deal, profile.id, payload.feed_is_public)
            deal.post_id = post.id

        repo.commit()
        repo.refresh(deal)
    except (GroupPermissionError, GroupProfileNotFoundError, GroupMemberFrozenError):
        repo.rollback()
        raise
    except Exception:
        repo.rollback()
        raise

    return _deal_to_response(deal)


def list_group_deals(
    repo: IGroupsRepository,
    group_id: UUID,
    user_id: UUID,
    page: int = 1,
    limit: int = 20,
) -> GroupDealListOut:
    _get_group_or_raise(repo, group_id)
    _require_member(repo, group_id, user_id)

    total = repo.count_deals(group_id)
    deals = repo.list_deals(group_id, page, limit)
    return GroupDealListOut(
        deals=[_deal_to_response(d) for d in deals],
        total=total,
        page=page,
        limit=limit,
    )


def get_group_deal(repo: IGroupsRepository, group_id: UUID, deal_id: UUID, user_id: UUID) -> GroupDealResponse:
    _get_group_or_raise(repo, group_id)
    _require_member(repo, group_id, user_id)
    deal = repo.get_deal(group_id, deal_id)
    if not deal:
        raise GroupNotFoundError("Deal not found")
    return _deal_to_response(deal)


def update_group_deal(
    repo: IGroupsRepository,
    group_id: UUID,
    deal_id: UUID,
    user_id: UUID,
    payload: GroupDealUpdate,
) -> GroupDealResponse:
    _get_group_or_raise(repo, group_id)
    deal = repo.get_deal(group_id, deal_id)
    if not deal:
        raise GroupNotFoundError("Deal not found")
    if deal.posted_by != user_id:
        raise GroupDealEditForbiddenError("Only the author can edit this deal")
    if deal.is_closed:
        raise GroupPermissionError("Closed deals cannot be edited")

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(deal, field, value)
    deal.updated_at = datetime.now(timezone.utc)

    repo.commit()
    repo.refresh(deal)
    return _deal_to_response(deal)


def close_group_deal(repo: IGroupsRepository, group_id: UUID, deal_id: UUID, user_id: UUID) -> GroupDealResponse:
    _get_group_or_raise(repo, group_id)
    deal = repo.get_deal(group_id, deal_id)
    if not deal:
        raise GroupNotFoundError("Deal not found")
    if deal.posted_by != user_id:
        raise GroupDealEditForbiddenError("Only the author can close this deal")

    deal.is_closed = not deal.is_closed
    deal.updated_at = datetime.now(timezone.utc)
    repo.commit()
    repo.refresh(deal)
    return _deal_to_response(deal)


def publish_group_deal(
    repo: IGroupsRepository,
    group_id: UUID,
    deal_id: UUID,
    user_id: UUID,
    profile_id: int,
    is_public: bool = True,
) -> GroupDealResponse:
    _get_group_or_raise(repo, group_id)
    deal = repo.get_deal(group_id, deal_id)
    if not deal:
        raise GroupNotFoundError("Deal not found")
    if deal.posted_by != user_id:
        raise GroupDealEditForbiddenError("Only the author can publish this deal")
    if deal.post_id is not None:
        raise GroupDealAlreadyPublishedError("Deal has already been published to the feed")

    try:
        post = _create_post_from_deal(repo, deal, profile_id, is_public)
        deal.post_id = post.id
        deal.updated_at = datetime.now(timezone.utc)
        repo.commit()
        repo.refresh(deal)
    except (GroupPermissionError, GroupNotFoundError, GroupDealAlreadyPublishedError, GroupDealEditForbiddenError):
        repo.rollback()
        raise
    except Exception:
        repo.rollback()
        raise

    return _deal_to_response(deal)
