"""
Group CRUD use cases — create, read, update, delete, list, and image upload.

All functions are pure business logic; no FastAPI imports.
Domain exceptions from app.modules.groups.domain.exceptions are raised on error.
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID


from app.modules.groups.data.models import (
    Group,
    GroupActivityCache,
    GroupEmbedding,
    GroupMember,
)
from app.modules.groups.application.schemas import (
    GroupCreate,
    GroupListOut,
    GroupOut,
    GroupPermissionsUpdate,
    GroupUpdate,
)
from app.modules.groups.domain.interfaces.repository import IGroupsRepository
from app.modules.groups.domain.exceptions import (
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
    path_from_url,
    public_url,
)
from app.modules.groups.recommendation.vectors import build_group_vector

log = logging.getLogger(__name__)

_GROUP_IMAGE_BUCKET = os.environ.get("GROUP_IMAGE_BUCKET", "group-image")
_GROUP_MEDIA_BUCKET = os.environ.get("GROUP_MEDIA_BUCKET", "group-media")

# ---------------------------------------------------------------------------
# Search intent parsing
# ---------------------------------------------------------------------------

_KNOWN_ROLES    = {"trader", "broker", "exporter"}
_ROLE_PLURAL    = {"traders": "trader", "brokers": "broker", "exporters": "exporter"}
_REGION_PATTERN = re.compile(r'\b(?:in|from|at)\s+(\w+)', re.IGNORECASE)
_STOP_WORDS     = {"groups", "group", "for", "the", "a", "an", "and", "of", "about"}


def _parse_group_search_intent(q: str) -> dict:
    """
    Extract target_role, commodity, region_market, and remaining name tokens
    from a free-text group search query.

    Examples
    --------
    "groups for traders"          -> target_role="trader"
    "rice traders in mumbai"      -> commodity="rice", target_role="trader", region_market="mumbai"
    "wheat exporters"             -> commodity="wheat", target_role="exporter"
    "cotton trading groups"       -> commodity="cotton"
    "brokers from delhi"          -> target_role="broker", region_market="delhi"
    """
    from app.modules.connections.application.use_cases.search_users import _KNOWN_COMMODITIES  # reuse same commodity list

    tokens = q.lower().split()
    target_role, commodity, region_market = None, None, None
    skip: set[str] = set()

    region_match = _REGION_PATTERN.search(q)
    if region_match:
        region_market = region_match.group(1).lower()
        skip.update(region_match.group(0).lower().split())

    remaining = []
    for token in tokens:
        if token in skip or token in _STOP_WORDS:
            continue
        normalized = _ROLE_PLURAL.get(token, token)
        if normalized in _KNOWN_ROLES:
            target_role = normalized
        elif token in _KNOWN_COMMODITIES:
            commodity = token
        else:
            remaining.append(token)

    return {
        "target_role":   target_role,
        "commodity":     commodity,
        "region_market": region_market,
        "name_q":        " ".join(remaining) or None,
    }


# ---------------------------------------------------------------------------
# Internal helpers (also re-used by other use case modules)
# ---------------------------------------------------------------------------




def _require_admin(repo: IGroupsRepository, group_id: UUID, user_id: UUID) -> None:
    membership = _get_membership(repo, group_id, user_id)
    if not membership or membership.role != "admin":
        raise GroupPermissionError("Admin access required")


def _require_member(repo: IGroupsRepository, group_id: UUID, user_id: UUID) -> None:
    membership = _get_membership(repo, group_id, user_id)
    if not membership:
        raise GroupPermissionError("Must be a group member")


def _build_group_out(group: Group, membership: Optional[GroupMember]) -> GroupOut:
    return GroupOut(
        id=group.id,
        name=group.name,
        description=group.description,
        group_rules=group.group_rules,
        image_url=group.image_url,
        commodity=group.commodity or [],
        target_roles=group.target_roles or [],
        region_market=group.region_market,
        region_lat=group.region_lat,
        region_lon=group.region_lon,
        # category=group.category,
        accessibility=group.accessibility,
        posting_perm=group.posting_perm,
        chat_perm=group.chat_perm,
        member_count=group.member_count,
        created_by=group.created_by,
        created_at=group.created_at,
        is_member=membership is not None,
        member_role=membership.role if membership else None,
        is_muted=membership.is_muted if membership else False,
        is_favorite=membership.is_favorite if membership else False,
    )


def _store_embedding(repo: IGroupsRepository, group: Group) -> None:
    """Build and persist the group's 11-dim embedding."""
    lat = group.region_lat or 20.5937   # default: centre of India
    lon = group.region_lon or 78.9629
    vec = build_group_vector(
        commodity_list=group.commodity or [],
        target_roles=group.target_roles or [],
        lat=lat,
        lon=lon,
    )
    repo.upsert_embedding(group.id, vec)


def _get_profile_or_raise(repo: IGroupsRepository, user_id: UUID):
    profile = repo.get_profile_by_user(user_id)
    if not profile:
        raise GroupProfileNotFoundError("Profile not found — complete onboarding first")
    return profile


def _get_group_or_raise(repo: IGroupsRepository, group_id: UUID) -> Group:
    group = repo.get_group(group_id)
    if not group:
        raise GroupNotFoundError("Group not found")
    return group


def _get_membership(repo: IGroupsRepository, group_id: UUID, user_id: UUID) -> Optional[GroupMember]:
    return repo.get_membership(group_id, user_id)


# ---------------------------------------------------------------------------
# Group CRUD
# ---------------------------------------------------------------------------

def create_group(repo: IGroupsRepository, user_id: UUID, payload: GroupCreate) -> GroupOut:
    """Creates a group. Creator is automatically added as admin."""
    _get_profile_or_raise(repo, user_id)

    try:
        group = Group(
            name=payload.name.strip(),
            description=payload.description,
            group_rules=payload.group_rules,
            image_url=payload.image_url,
            commodity=payload.commodities or [],
            target_roles=payload.target_roles or [],
            region_market=payload.region_market,
            region_lat=payload.region_lat,
            region_lon=payload.region_lon,
            category=payload.category,
            accessibility=payload.accessibility,
            posting_perm=payload.posting_perm,
            chat_perm=payload.chat_perm,
            created_by=user_id,
            member_count=1,
        )
        repo.add(group)
        repo.flush()  # get group.id

        # Creator is admin
        repo.add(GroupMember(group_id=group.id, user_id=user_id, role="admin"))

        # Add initial members if provided (they join as regular members)
        added_ids = {user_id}
        for uid in (payload.initial_member_ids or []):
            if uid not in added_ids:
                repo.add(GroupMember(group_id=group.id, user_id=uid, role="member"))
                added_ids.add(uid)

        group.member_count = len(added_ids)

        # Seed activity cache
        repo.add(GroupActivityCache(group_id=group.id))

        # Build & store embedding
        _store_embedding(repo, group)

        repo.commit()
        repo.refresh(group)
    except Exception:
        repo.rollback()
        raise

    membership = _get_membership(repo, group.id, user_id)
    return _build_group_out(group, membership)


def list_groups(
    repo: IGroupsRepository,
    user_id: UUID,
    *,
    commodity: Optional[str] = None,
    accessibility: Optional[str] = None,
    search: Optional[str] = None,
    region_market: Optional[str] = None,
    target_role: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
) -> GroupListOut:
    # Smart intent parsing — only when search is the sole filter provided
    name_q = search
    if search and not any([commodity, target_role, region_market]):
        intent = _parse_group_search_intent(search)
        target_role   = intent["target_role"]
        commodity     = intent["commodity"]
        region_market = intent["region_market"]
        name_q        = intent["name_q"]  # leftover tokens become name search

    groups, total = repo.search_groups(
        commodity=commodity, accessibility=accessibility, name_q=name_q,
        region_market=region_market, target_role=target_role,
        page=page, per_page=per_page,
    )

    # One membership query for the whole page. Doing it per group was an N+1:
    # 26 groups cost 22 queries, and each one is a round trip to the database.
    memberships = repo.get_memberships([g.id for g in groups], user_id)
    out = [_build_group_out(g, memberships.get(g.id)) for g in groups]

    return GroupListOut(groups=out, total=total, page=page, per_page=per_page)


def get_group(repo: IGroupsRepository, group_id: UUID, user_id: UUID) -> GroupOut:
    group = _get_group_or_raise(repo, group_id)
    membership = _get_membership(repo, group_id, user_id)
    return _build_group_out(group, membership)


def update_group(
    repo: IGroupsRepository, group_id: UUID, user_id: UUID, payload: GroupUpdate
) -> GroupOut:
    _require_admin(repo, group_id, user_id)
    group = _get_group_or_raise(repo, group_id)

    data = payload.model_dump(exclude_unset=True)
    if "commodities" in data:
        group.commodity = data.pop("commodities")
    for field, value in data.items():
        setattr(group, field, value)

    # Rebuild embedding when location or commodity changes
    if any(k in data for k in ("commodities", "region_lat", "region_lon")):
        _store_embedding(repo, group)

    repo.commit()
    repo.refresh(group)
    membership = _get_membership(repo, group_id, user_id)
    return _build_group_out(group, membership)


def update_permissions(
    repo: IGroupsRepository, group_id: UUID, user_id: UUID, payload: GroupPermissionsUpdate
) -> GroupOut:
    _require_admin(repo, group_id, user_id)
    group = _get_group_or_raise(repo, group_id)

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(group, field, value)

    repo.commit()
    repo.refresh(group)
    membership = _get_membership(repo, group_id, user_id)
    return _build_group_out(group, membership)


async def delete_group(repo: IGroupsRepository, group_id: UUID, user_id: UUID) -> list[UUID]:
    """Deletes the group and, best-effort, the storage objects nothing else
    owns (the cover image, every GroupMedia file — group_members/activity_cache/
    embedding/media rows themselves are handled by the existing ORM cascade +
    DB-level ON DELETE CASCADE on group_deals/group_join_requests).

    Returns the member user_ids as they were immediately before deletion, so
    the router can evict their sockets from the group's realtime room — once
    the group is gone, GroupMember rows (and with them repo.list_members) are
    gone too.

    Note: group chat messages (chat.messages with context_type='group',
    context_id=group_id) are NOT cleaned up here — there is no FK from chat's
    tables to groups.id (chat stores context_id as a bare UUID, not a foreign
    key), and reaching into chat's tables from this module would cross the
    module boundary chat's own data layer owns. Pre-existing gap, not
    introduced by this endpoint; needs a chat-side interface if it's ever
    fixed, not a direct table write from here.
    """
    _require_admin(repo, group_id, user_id)
    group = _get_group_or_raise(repo, group_id)

    # Captured before delete — the group row (and everything that cascades
    # with it) is gone once committed below.
    image_url = group.image_url
    media_paths = [m.storage_path for m in repo.list_media(group_id, page=1, limit=10_000)]
    member_ids = [m.user_id for m in repo.list_members(group_id, page=1, limit=10_000)]

    try:
        repo.delete(group)
        repo.commit()
    except Exception:
        repo.rollback()
        raise

    if image_url:
        try:
            old_path = path_from_url(_GROUP_IMAGE_BUCKET, image_url)
            await delete_object(_GROUP_IMAGE_BUCKET, old_path)
        except StorageError:
            # Orphaned object — the row is gone, the bytes are not. Billable.
            log.warning("could not delete group image for deleted group %s", group_id)

    for storage_path in media_paths:
        try:
            await delete_object(_GROUP_MEDIA_BUCKET, storage_path)
        except StorageError:
            log.warning("could not delete group media %s for deleted group %s", storage_path, group_id)

    return member_ids


# ---------------------------------------------------------------------------
# Group image upload (group-image bucket)
# ---------------------------------------------------------------------------

async def get_group_image_upload_url(user_id: UUID, content_type: str) -> dict:
    """
    Returns a signed upload URL for the group's cover image.
    Flow: client PUTs image bytes to upload_url, then passes image_url
    in GroupCreate.image_url when creating the group (or GroupUpdate.image_url
    when updating).
    """
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise GroupValidationError(
            f"Unsupported type '{content_type}'. Allowed: image/jpeg, image/png, image/webp."
        )

    ext = ext_for(content_type)
    path = f"{user_id}/{uuid.uuid4()}{ext}"

    try:
        result = await generate_signed_upload_url(_GROUP_IMAGE_BUCKET, path)
    except StorageError as e:
        raise GroupStorageError(str(e))

    return {
        **result,
        "image_url": public_url(_GROUP_IMAGE_BUCKET, path),
        "content_type": content_type,
    }
