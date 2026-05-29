"""
Groups service layer — pure business logic, no FastAPI imports.

Verification gate:
  Only users whose profile.is_verified == True may create a group.

Role mapping (matches existing lookup table seeds):
  1 = Trader   → "trader"
  2 = Broker   → "broker"
  3 = Exporter → "exporter"
"""
from __future__ import annotations

import os
import re
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import or_, text
from sqlalchemy.orm import Session, joinedload

from app.modules.profile.models import Business, Profile, Profile_Commodity, Role
from app.modules.groups.models import (
    Group,
    GroupActivityCache,
    GroupEmbedding,
    GroupJoinRequest,
    GroupMedia,
    GroupMember,
)
from app.modules.groups.schemas import (
    GroupCreate,
    GroupJoinRequestListOut,
    GroupJoinRequestOut,
    GroupListOut,
    GroupMediaOut,
    GroupMediaUploadOut,
    GroupMemberOut,
    GroupOut,
    GroupPermissionsUpdate,
    GroupSuggestionOut,
    GroupUpdate,
    InviteLinkOut,
)
from app.shared.utils.storage import (
    ALLOWED_IMAGE_TYPES,
    StorageError,
    delete_object,
    ext_for,
    generate_signed_upload_url,
    public_url,
)

_GROUP_IMAGE_BUCKET = os.environ.get("GROUP_IMAGE_BUCKET", "group-image")
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
from app.modules.groups.vector import (
    build_group_vector,
    build_match_reasons,
    compute_activity_score,
    compute_final_score,
)
from app.modules.connections.encoding.vector import build_query_vector

# role_id → string name used in vector encoding
ROLE_ID_TO_NAME = {1: "trader", 2: "broker", 3: "exporter"}
TOP_K = 20

# ---------------------------------------------------------------------------
# Group search intent parsing
# ---------------------------------------------------------------------------

_KNOWN_ROLES       = {"trader", "broker", "exporter"}
_ROLE_PLURAL       = {"traders": "trader", "brokers": "broker", "exporters": "exporter"}
_REGION_PATTERN    = re.compile(r'\b(?:in|from|at)\s+(\w+)', re.IGNORECASE)
_STOP_WORDS        = {"groups", "group", "for", "the", "a", "an", "and", "of", "about"}


def _parse_group_search_intent(q: str) -> dict:
    """
    Extract target_role, commodity, region_market, and remaining name tokens
    from a free-text group search query.

    Examples
    --------
    "groups for traders"          → target_role="trader"
    "rice traders in mumbai"      → commodity="rice", target_role="trader", region_market="mumbai"
    "wheat exporters"             → commodity="wheat", target_role="exporter"
    "cotton trading groups"       → commodity="cotton"
    "brokers from delhi"          → target_role="broker", region_market="delhi"
    """
    from app.modules.connections.service import _KNOWN_COMMODITIES  # reuse same commodity list

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
        "target_role":    target_role,
        "commodity":      commodity,
        "region_market":  region_market,
        "name_q":         " ".join(remaining) or None,
    }


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class GroupNotFoundError(Exception):
    pass

class GroupConflictError(Exception):
    pass

class GroupPermissionError(Exception):
    pass

class GroupValidationError(Exception):
    pass

class GroupStorageError(Exception):
    pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_profile_or_raise(db: Session, user_id: UUID) -> Profile:
    profile = (
        db.query(Profile)
        .options(
            joinedload(Profile.business),
            joinedload(Profile.commodities).joinedload(Profile_Commodity.commodity),
        )
        .filter(Profile.users_id == user_id)
        .first()
    )
    if not profile:
        raise GroupNotFoundError("Profile not found — complete onboarding first")
    return profile


def _get_group_or_raise(db: Session, group_id: UUID) -> Group:
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise GroupNotFoundError("Group not found")
    return group


def _get_membership(
    db: Session, group_id: UUID, user_id: UUID
) -> Optional[GroupMember]:
    return (
        db.query(GroupMember)
        .filter(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
        .first()
    )


def _require_admin(db: Session, group_id: UUID, user_id: UUID) -> None:
    membership = _get_membership(db, group_id, user_id)
    if not membership or membership.role != "admin":
        raise GroupPermissionError("Admin access required")


def _require_member(db: Session, group_id: UUID, user_id: UUID) -> None:
    membership = _get_membership(db, group_id, user_id)
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


def _store_embedding(db: Session, group: Group) -> None:
    """Build and persist the group's 11-dim embedding."""
    lat = group.region_lat or 20.5937   # default: centre of India
    lon = group.region_lon or 78.9629
    vec = build_group_vector(
        commodity_list=group.commodity or [],
        target_roles=group.target_roles or [],
        lat=lat,
        lon=lon,
    )
    existing = db.query(GroupEmbedding).filter(
        GroupEmbedding.group_id == group.id
    ).first()
    if existing:
        existing.embedding = vec
        existing.updated_at = datetime.now(timezone.utc)
    else:
        db.add(GroupEmbedding(group_id=group.id, embedding=vec))


# ---------------------------------------------------------------------------
# Group CRUD
# ---------------------------------------------------------------------------

def create_group(db: Session, user_id: UUID, payload: GroupCreate) -> GroupOut:
    """
    Creates a group.  Only verified users (profile.is_verified == True) may create.
    Creator is automatically added as admin.
    """
    profile = _get_profile_or_raise(db, user_id)

    if not (profile.is_user_verified and profile.is_business_verified):
        raise GroupPermissionError(
            "Only fully verified users (KYC + KYB) can create groups. "
            "Complete profile verification first."
        )

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
        db.add(group)
        db.flush()  # get group.id

        # Creator is admin
        db.add(GroupMember(group_id=group.id, user_id=user_id, role="admin"))

        # Add initial members if provided (they join as regular members)
        added_ids = {user_id}
        for uid in (payload.initial_member_ids or []):
            if uid not in added_ids:
                db.add(GroupMember(group_id=group.id, user_id=uid, role="member"))
                added_ids.add(uid)

        group.member_count = len(added_ids)

        # Seed activity cache
        db.add(GroupActivityCache(group_id=group.id))

        # Build & store embedding
        _store_embedding(db, group)

        db.commit()
        db.refresh(group)
    except Exception:
        db.rollback()
        raise

    membership = _get_membership(db, group.id, user_id)
    return _build_group_out(group, membership)


def list_groups(
    db: Session,
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
        name_q        = intent["name_q"]   # leftover tokens become name search

    query = db.query(Group)

    if commodity:
        query = query.filter(Group.commodity.contains([commodity]))

    if accessibility:
        query = query.filter(Group.accessibility == accessibility)

    if name_q:
        # search group name AND region_market so bare city names (e.g. "nagpur") hit both
        query = query.filter(
            or_(
                Group.name.ilike(f"%{name_q}%"),
                Group.region_market.ilike(f"%{name_q}%"),
            )
        )

    if region_market:
        query = query.filter(Group.region_market.ilike(f"%{region_market}%"))

    if target_role:
        # JSONB contains is case-sensitive; also match groups whose name contains the role word
        query = query.filter(
            or_(
                Group.target_roles.contains([target_role]),
                Group.name.ilike(f"%{target_role}%"),
            )
        )

    total = query.count()
    groups = (
        query.order_by(Group.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    out = []
    for g in groups:
        membership = _get_membership(db, g.id, user_id)
        out.append(_build_group_out(g, membership))

    return GroupListOut(groups=out, total=total, page=page, per_page=per_page)


def get_group(db: Session, group_id: UUID, user_id: UUID) -> GroupOut:
    group = _get_group_or_raise(db, group_id)
    membership = _get_membership(db, group_id, user_id)
    return _build_group_out(group, membership)


def update_group(
    db: Session, group_id: UUID, user_id: UUID, payload: GroupUpdate
) -> GroupOut:
    _require_admin(db, group_id, user_id)
    group = _get_group_or_raise(db, group_id)

    data = payload.model_dump(exclude_unset=True)
    if "commodities" in data:
        group.commodity = data.pop("commodities")
    for field, value in data.items():
        setattr(group, field, value)

    # Rebuild embedding when location or commodity changes
    if any(k in data for k in ("commodities", "region_lat", "region_lon")):
        _store_embedding(db, group)

    db.commit()
    db.refresh(group)
    membership = _get_membership(db, group_id, user_id)
    return _build_group_out(group, membership)


def update_permissions(
    db: Session, group_id: UUID, user_id: UUID, payload: GroupPermissionsUpdate
) -> GroupOut:
    _require_admin(db, group_id, user_id)
    group = _get_group_or_raise(db, group_id)

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(group, field, value)

    db.commit()
    db.refresh(group)
    membership = _get_membership(db, group_id, user_id)
    return _build_group_out(group, membership)


def delete_group(db: Session, group_id: UUID, user_id: UUID) -> None:
    _require_admin(db, group_id, user_id)
    group = _get_group_or_raise(db, group_id)
    try:
        db.delete(group)
        db.commit()
    except Exception:
        db.rollback()
        raise


# ---------------------------------------------------------------------------
# Membership operations
# ---------------------------------------------------------------------------

def join_group(db: Session, group_id: UUID, user_id: UUID) -> dict:
    group = _get_group_or_raise(db, group_id)

    if group.accessibility == "invite_only":
        raise GroupPermissionError("This group is invite-only. Use an invite link.")

    existing = _get_membership(db, group_id, user_id)
    if existing:
        raise GroupConflictError("Already a member of this group")

    if group.accessibility == "private":
        existing_req = (
            db.query(GroupJoinRequest)
            .filter(
                GroupJoinRequest.group_id == group_id,
                GroupJoinRequest.user_id == user_id,
                GroupJoinRequest.status == "pending",
            )
            .first()
        )
        if existing_req:
            raise GroupConflictError("Join request already pending for this group")

        try:
            db.add(GroupJoinRequest(group_id=group_id, user_id=user_id))
            db.commit()
        except Exception:
            db.rollback()
            raise

        return {"status": "pending", "message": "Join request sent. Waiting for admin approval."}

    try:
        db.add(GroupMember(group_id=group_id, user_id=user_id, role="member"))
        group.member_count += 1
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {"status": "joined", "role": "member", "joined_at": datetime.now(timezone.utc).isoformat()}


# ---------------------------------------------------------------------------
# Join request management (private groups)
# ---------------------------------------------------------------------------

def get_join_requests(
    db: Session,
    group_id: UUID,
    user_id: UUID,
    status: Optional[str] = "pending",
    page: int = 1,
    limit: int = 20,
) -> GroupJoinRequestListOut:
    _require_admin(db, group_id, user_id)
    _get_group_or_raise(db, group_id)

    query = db.query(GroupJoinRequest).filter(GroupJoinRequest.group_id == group_id)
    if status:
        query = query.filter(GroupJoinRequest.status == status)

    total = query.count()
    requests = (
        query.order_by(GroupJoinRequest.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    return GroupJoinRequestListOut(
        requests=[GroupJoinRequestOut.model_validate(r) for r in requests],
        total=total,
        page=page,
        limit=limit,
    )


def resolve_join_request(
    db: Session,
    group_id: UUID,
    request_id: UUID,
    admin_id: UUID,
    action: str,  # "approve" | "reject"
) -> dict:
    _require_admin(db, group_id, admin_id)
    group = _get_group_or_raise(db, group_id)

    req = (
        db.query(GroupJoinRequest)
        .filter(
            GroupJoinRequest.id == request_id,
            GroupJoinRequest.group_id == group_id,
        )
        .first()
    )
    if not req:
        raise GroupNotFoundError("Join request not found")
    if req.status != "pending":
        raise GroupConflictError(f"Request already {req.status}")

    req.status = "approved" if action == "approve" else "rejected"
    req.resolved_at = datetime.now(timezone.utc)
    req.resolved_by = admin_id

    if action == "approve":
        existing = _get_membership(db, group_id, req.user_id)
        if not existing:
            db.add(GroupMember(group_id=group_id, user_id=req.user_id, role="member"))
            group.member_count += 1

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {"request_id": str(request_id), "status": req.status}


def get_my_admin_pending_requests(
    db: Session,
    user_id: UUID,
    page: int = 1,
    limit: int = 20,
):
    """
    Returns all pending join requests across every group the caller admins.
    Scoped entirely to user_id from JWT — no other user's data is ever returned.
    """
    from app.modules.groups.schemas import AdminPendingRequestOut, AdminPendingRequestsListOut

    admin_group_ids = [
        row.group_id
        for row in db.query(GroupMember.group_id)
        .filter(GroupMember.user_id == user_id, GroupMember.role == "admin")
        .all()
    ]

    if not admin_group_ids:
        return AdminPendingRequestsListOut(requests=[], total=0, page=page, limit=limit)

    query = (
        db.query(GroupJoinRequest, Group.name)
        .join(Group, Group.id == GroupJoinRequest.group_id)
        .filter(
            GroupJoinRequest.group_id.in_(admin_group_ids),
            GroupJoinRequest.status == "pending",
        )
    )

    total = query.count()
    rows = (
        query.order_by(GroupJoinRequest.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    return AdminPendingRequestsListOut(
        requests=[
            AdminPendingRequestOut(
                id=req.id,
                group_id=req.group_id,
                group_name=group_name,
                user_id=req.user_id,
                status=req.status,
                created_at=req.created_at,
            )
            for req, group_name in rows
        ],
        total=total,
        page=page,
        limit=limit,
    )


def leave_group(db: Session, group_id: UUID, user_id: UUID) -> None:
    group = _get_group_or_raise(db, group_id)
    membership = _get_membership(db, group_id, user_id)

    if not membership:
        raise GroupNotFoundError("Not a member of this group")

    if membership.role == "admin":
        # Check if there's another admin
        other_admin = (
            db.query(GroupMember)
            .filter(
                GroupMember.group_id == group_id,
                GroupMember.user_id != user_id,
                GroupMember.role == "admin",
            )
            .first()
        )
        if not other_admin:
            raise GroupPermissionError(
                "You are the sole admin. Assign another admin before leaving."
            )

    try:
        db.delete(membership)
        group.member_count = max(0, group.member_count - 1)
        db.commit()
    except Exception:
        db.rollback()
        raise


def get_members(
    db: Session,
    group_id: UUID,
    user_id: UUID,
    page: int = 1,
    limit: int = 20,
) -> dict:
    _get_group_or_raise(db, group_id)

    from sqlalchemy import case
    total = db.query(GroupMember).filter(GroupMember.group_id == group_id).count()
    memberships = (
        db.query(GroupMember)
        .filter(GroupMember.group_id == group_id)
        .order_by(
            case((GroupMember.role == "admin", 0), else_=1),
            GroupMember.joined_at.asc(),
        )
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    member_ids = [m.user_id for m in memberships]
    profiles = (
        db.query(Profile)
        .options(joinedload(Profile.role))
        .filter(Profile.users_id.in_(member_ids))
        .all()
    )
    profile_map = {p.users_id: p for p in profiles}

    out: list[GroupMemberOut] = []
    for m in memberships:
        p = profile_map.get(m.user_id)
        out.append(
            GroupMemberOut(
                user_id=m.user_id,
                name=p.name if p else "Unknown",
                role=p.role.name if p and p.role else "Unknown",
                avatar_url=p.avatar_url if p else None,
                is_admin=(m.role == "admin"),
                is_user_verified=p.is_user_verified if p else False,
                is_business_verified=p.is_business_verified if p else False,
                member_role=m.role,
                is_frozen=m.is_frozen,
                is_muted=m.is_muted,
                joined_at=m.joined_at,
            )
        )

    return {"members": out, "total": total, "page": page, "limit": limit}


def add_members(
    db: Session, group_id: UUID, requester_id: UUID, user_ids: list[UUID]
) -> dict:
    _require_admin(db, group_id, requester_id)
    group = _get_group_or_raise(db, group_id)

    added = []
    for uid in user_ids:
        if not _get_membership(db, group_id, uid):
            db.add(GroupMember(group_id=group_id, user_id=uid, role="member"))
            added.append(str(uid))

    group.member_count += len(added)
    db.commit()
    return {"added": added, "count": len(added)}


def remove_member(
    db: Session, group_id: UUID, requester_id: UUID, target_user_id: UUID
) -> None:
    _require_admin(db, group_id, requester_id)
    membership = _get_membership(db, group_id, target_user_id)
    if not membership:
        raise GroupNotFoundError("User is not a member of this group")

    group = _get_group_or_raise(db, group_id)
    try:
        db.delete(membership)
        group.member_count = max(0, group.member_count - 1)
        db.commit()
    except Exception:
        db.rollback()
        raise


def set_member_frozen(
    db: Session,
    group_id: UUID,
    requester_id: UUID,
    target_user_id: UUID,
    frozen: bool,
) -> dict:
    _require_admin(db, group_id, requester_id)
    membership = _get_membership(db, group_id, target_user_id)
    if not membership:
        raise GroupNotFoundError("User is not a member of this group")

    membership.is_frozen = frozen
    db.commit()
    return {"user_id": str(target_user_id), "is_frozen": frozen}


def toggle_mute(db: Session, group_id: UUID, user_id: UUID) -> dict:
    membership = _get_membership(db, group_id, user_id)
    if not membership:
        raise GroupNotFoundError("Not a member of this group")

    membership.is_muted = not membership.is_muted
    db.commit()
    return {"is_muted": membership.is_muted}


def toggle_favorite(db: Session, group_id: UUID, user_id: UUID) -> dict:
    membership = _get_membership(db, group_id, user_id)
    if not membership:
        raise GroupNotFoundError("Not a member of this group")

    membership.is_favorite = not membership.is_favorite
    db.commit()
    return {"is_favorite": membership.is_favorite}


# ---------------------------------------------------------------------------
# Invite link
# ---------------------------------------------------------------------------

def get_or_create_invite_link(
    db: Session, group_id: UUID, user_id: UUID, base_url: str = "https://api.vanijyaa.com"
) -> InviteLinkOut:
    _require_member(db, group_id, user_id)
    group = _get_group_or_raise(db, group_id)

    if not group.invite_link_token:
        group.invite_link_token = secrets.token_urlsafe(16)
        db.commit()
        db.refresh(group)

    return InviteLinkOut(
        invite_link_token=group.invite_link_token,
        join_url=f"{base_url}/api/v1/groups/join-by-link/{group.invite_link_token}",
    )


def join_by_invite_link(
    db: Session, token: str, user_id: UUID
) -> dict:
    group = db.query(Group).filter(Group.invite_link_token == token).first()
    if not group:
        raise GroupNotFoundError("Invalid or expired invite link")

    existing = _get_membership(db, group.id, user_id)
    if existing:
        raise GroupConflictError("Already a member of this group")

    try:
        db.add(GroupMember(group_id=group.id, user_id=user_id, role="member"))
        group.member_count += 1
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "group_id": str(group.id),
        "group_name": group.name,
        "role": "member",
        "joined_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Group Recommendation Engine
# ---------------------------------------------------------------------------

def get_group_suggestions(
    db: Session,
    user_id: UUID,
    top_k: int = TOP_K,
    page: int = 1,
    limit: int = 20,
) -> dict:
    """
    Two-stage group recommendation:
      Stage 1 — pgvector HNSW cosine ANN (<=> operator) pre-filters candidates.
      Stage 2 — activity reranking via group_activity_cache.
      Final    — weighted blend (75 % semantic + 25 % activity).
    """
    # ── 1. Load user profile ────────────────────────────────────────────────
    profile = _get_profile_or_raise(db, user_id)

    user_commodities = [pc.commodity.name.lower() for pc in profile.commodities]
    user_role = ROLE_ID_TO_NAME.get(profile.role_id, "trader")

    if not profile.business:
        raise GroupValidationError(
            "Business profile not set up — complete onboarding to get group suggestions."
        )

    want_vec = build_query_vector(
        commodity_list=user_commodities,
        role=user_role,
        lat=float(profile.business.latitude),
        lon=float(profile.business.longitude),
        qty_min=int(profile.quantity_min),
        qty_max=int(profile.quantity_max),
    )

    vec_str = "[" + ",".join(str(v) for v in want_vec) + "]"

    # ── 2. Get user's current group memberships ─────────────────────────────
    member_set = {
        row[0]
        for row in db.query(GroupMember.group_id)
        .filter(GroupMember.user_id == user_id)
        .all()
    }

    # ── 3. HNSW ANN: fetch top candidates, excluding private groups ─────────
    # Overfetch (top_k * 4) to allow Python-side member filtering.
    candidate_rows = db.execute(
        text("""
            SELECT ge.group_id,
                   1 - (ge.embedding <=> CAST(:vec AS vector)) AS similarity
            FROM group_embeddings ge
            JOIN groups g ON g.id = ge.group_id
            WHERE ge.embedding IS NOT NULL
              AND g.accessibility != 'private'
            ORDER BY ge.embedding <=> CAST(:vec AS vector)
            LIMIT :limit
        """),
        {"vec": vec_str, "limit": top_k * 4},
    ).mappings().all()

    # Filter out groups the user already belongs to
    candidates = [
        (r["group_id"], float(r["similarity"]))
        for r in candidate_rows
        if r["group_id"] not in member_set
    ][:top_k * 2]  # keep a buffer for activity reranking

    if not candidates:
        return {"total": 0, "page": page, "limit": limit, "results": []}

    # ── 4. Load groups + activity caches in bulk ────────────────────────────
    group_ids = [gid for gid, _ in candidates]
    sim_by_id = {gid: sim for gid, sim in candidates}

    groups = {
        g.id: g
        for g in db.query(Group).filter(Group.id.in_(group_ids)).all()
    }
    activities = {
        a.group_id: a
        for a in db.query(GroupActivityCache)
        .filter(GroupActivityCache.group_id.in_(group_ids))
        .all()
    }

    # ── 5. Activity reranking — weighted blend ──────────────────────────────
    scored: list[tuple[float, Group, float, float]] = []
    for gid, sim in candidates:
        group = groups.get(gid)
        if group is None:
            continue

        cache = activities.get(gid)
        act = compute_activity_score(
            messages_24h=cache.messages_24h if cache else 0,
            active_members_7d=cache.active_members_7d if cache else 0,
            member_growth_7d=cache.member_growth_7d if cache else 0,
        )
        final = compute_final_score(sim, act)
        scored.append((final, group, sim, act))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_k]

    # ── 6. Build response ───────────────────────────────────────────────────
    all_results: list[GroupSuggestionOut] = []
    for final_score, group, sim, act in top:
        reasons = build_match_reasons(
            user_commodities=user_commodities,
            user_role=user_role,
            group_commodities=group.commodity or [],
            group_target_roles=group.target_roles or [],
            cosine_sim=sim,
            act_score=act,
        )
        all_results.append(
            GroupSuggestionOut(
                group=_build_group_out(group, None),
                match_score=final_score,
                match_reasons=reasons,
            )
        )

    start = (page - 1) * limit
    return {
        "total": len(all_results),
        "page": page,
        "limit": limit,
        "results": all_results[start : start + limit],
    }


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


# ---------------------------------------------------------------------------
# Group media upload (group-media bucket)
# ---------------------------------------------------------------------------

async def get_group_media_upload_url(
    db: Session,
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

    _require_member(db, group_id, user_id)
    _get_group_or_raise(db, group_id)

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
    db.add(record)
    db.commit()

    return GroupMediaUploadOut(
        media_id=media_id,
        upload_url=result["upload_url"],
        media_url=media_url,
        media_type=media_category,
        expires_at=result["expires_at"],
    )


def list_group_media(
    db: Session,
    group_id: UUID,
    user_id: UUID,
    page: int = 1,
    limit: int = 20,
) -> dict:
    _get_group_or_raise(db, group_id)
    _require_member(db, group_id, user_id)

    total = db.query(GroupMedia).filter(GroupMedia.group_id == group_id).count()
    items = (
        db.query(GroupMedia)
        .filter(GroupMedia.group_id == group_id)
        .order_by(GroupMedia.uploaded_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    return {
        "media": [GroupMediaOut.model_validate(m) for m in items],
        "total": total,
        "page": page,
        "limit": limit,
    }


async def delete_group_media(
    db: Session,
    group_id: UUID,
    media_id: UUID,
    user_id: UUID,
) -> None:
    """Admin or the uploader can delete a media item."""
    _get_group_or_raise(db, group_id)

    record = (
        db.query(GroupMedia)
        .filter(GroupMedia.id == media_id, GroupMedia.group_id == group_id)
        .first()
    )
    if not record:
        raise GroupNotFoundError("Media not found")

    membership = _get_membership(db, group_id, user_id)
    is_admin = membership and membership.role == "admin"
    is_uploader = record.uploaded_by == user_id

    if not (is_admin or is_uploader):
        raise GroupPermissionError("Only admins or the uploader can delete media")

    try:
        await delete_object(_GROUP_MEDIA_BUCKET, record.storage_path)
    except StorageError:
        pass  # best-effort — remove DB record regardless

    db.delete(record)
    db.commit()
