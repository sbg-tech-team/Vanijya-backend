"""
Group membership use cases — join, leave, invite links, member management,
join-request lifecycle, and per-membership preference toggles.

All functions are pure business logic; no FastAPI imports.
Domain exceptions from app.modules.groups.domain.exceptions are raised on error.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID


from app.modules.groups.application.use_cases.record_view import MODULE
from app.recommendation.amplify import commodity_ids_for, write_commodity_signals
from app.recommendation.session_taste import ActionType
from app.modules.groups.data.models import (
    Group,
    GroupJoinRequest,
    GroupMember,
)
from app.modules.groups.application.schemas import (
    GroupJoinRequestListOut,
    GroupJoinRequestOut,
    GroupMemberOut,
    InviteLinkOut,
)
from app.modules.groups.domain.interfaces.repository import IGroupsRepository
from app.modules.groups.domain.exceptions import (
    GroupAlreadyMemberError,
    GroupInviteOnlyError,
    GroupJoinRequestAlreadyPendingError,
    GroupJoinRequestAlreadyResolvedError,
    GroupJoinRequestNotFoundError,
    GroupMemberNotFoundError,
    GroupNotFoundError,
    GroupPermissionError,
    GroupSoleAdminLeaveError,
)

# Re-import shared helpers from create_group to avoid duplication
from app.modules.groups.application.use_cases.create_group import (
    _get_group_or_raise,
    _get_membership,
    _require_admin,
    _require_member,
)


# ---------------------------------------------------------------------------
# Membership operations
# ---------------------------------------------------------------------------

def join_group(
    repo: IGroupsRepository,
    group_id: UUID,
    user_id: UUID,
    rc=None,
    actor_profile_id: int | None = None,
) -> dict:
    """`rc`/`actor_profile_id` drive the app_old GROUP_JOIN taste signal; both
    optional so existing callers keep working (signal is simply skipped)."""
    group = _get_group_or_raise(repo, group_id)

    if group.accessibility == "invite_only":
        raise GroupInviteOnlyError("This group is invite-only. Use an invite link.")

    existing = _get_membership(repo, group_id, user_id)
    if existing:
        raise GroupAlreadyMemberError("Already a member of this group")

    def _record() -> None:
        # group_join — strong intent. Commodities resolved from the group itself.
        # app_old fires this on BOTH the request-sent and joined paths.
        if actor_profile_id is not None:
            write_commodity_signals(
                rc, actor_profile_id, MODULE,
                commodity_ids_for(repo.session, group.commodity or []),
                ActionType.GROUP_JOIN,
            )

    if group.accessibility == "private":
        existing_req = repo.get_pending_join_request(group_id, user_id)
        if existing_req:
            raise GroupJoinRequestAlreadyPendingError("Join request already pending for this group")

        try:
            repo.add(GroupJoinRequest(group_id=group_id, user_id=user_id))
            repo.commit()
        except Exception:
            repo.rollback()
            raise

        _record()
        return {"status": "pending", "message": "Join request sent. Waiting for admin approval."}

    try:
        repo.add(GroupMember(group_id=group_id, user_id=user_id, role="member"))
        group.member_count += 1
        repo.commit()
    except Exception:
        repo.rollback()
        raise

    _record()
    return {"status": "joined", "role": "member", "joined_at": datetime.now(timezone.utc).isoformat()}


def leave_group(repo: IGroupsRepository, group_id: UUID, user_id: UUID) -> None:
    group = _get_group_or_raise(repo, group_id)
    membership = _get_membership(repo, group_id, user_id)

    if not membership:
        raise GroupMemberNotFoundError("Not a member of this group")

    if membership.role == "admin":
        # Check if there's another admin
        other_admin = repo.get_other_admin(group_id, user_id)
        if not other_admin:
            raise GroupSoleAdminLeaveError(
                "You are the sole admin. Assign another admin before leaving."
            )

    try:
        repo.delete(membership)
        group.member_count = max(0, group.member_count - 1)
        repo.commit()
    except Exception:
        repo.rollback()
        raise


def get_members(
    repo: IGroupsRepository,
    group_id: UUID,
    user_id: UUID,
    page: int = 1,
    limit: int = 20,
) -> dict:
    _get_group_or_raise(repo, group_id)

    total = repo.count_members(group_id)
    memberships = repo.list_members(group_id, page, limit)

    member_ids = [m.user_id for m in memberships]
    profile_map = repo.get_profiles_with_role(member_ids)

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
    repo: IGroupsRepository, group_id: UUID, requester_id: UUID, user_ids: list[UUID]
) -> dict:
    _require_admin(repo, group_id, requester_id)
    group = _get_group_or_raise(repo, group_id)

    added = []
    for uid in user_ids:
        if not _get_membership(repo, group_id, uid):
            repo.add(GroupMember(group_id=group_id, user_id=uid, role="member"))
            added.append(str(uid))

    group.member_count += len(added)
    repo.commit()
    return {"added": added, "count": len(added)}


def remove_member(
    repo: IGroupsRepository, group_id: UUID, requester_id: UUID, target_user_id: UUID
) -> None:
    _require_admin(repo, group_id, requester_id)
    membership = _get_membership(repo, group_id, target_user_id)
    if not membership:
        raise GroupMemberNotFoundError("User is not a member of this group")

    group = _get_group_or_raise(repo, group_id)
    try:
        repo.delete(membership)
        group.member_count = max(0, group.member_count - 1)
        repo.commit()
    except Exception:
        repo.rollback()
        raise


def set_member_frozen(
    repo: IGroupsRepository,
    group_id: UUID,
    requester_id: UUID,
    target_user_id: UUID,
    frozen: bool,
) -> dict:
    _require_admin(repo, group_id, requester_id)
    membership = _get_membership(repo, group_id, target_user_id)
    if not membership:
        raise GroupMemberNotFoundError("User is not a member of this group")

    membership.is_frozen = frozen
    repo.commit()
    return {"user_id": str(target_user_id), "is_frozen": frozen}


def toggle_mute(repo: IGroupsRepository, group_id: UUID, user_id: UUID) -> dict:
    membership = _get_membership(repo, group_id, user_id)
    if not membership:
        raise GroupMemberNotFoundError("Not a member of this group")

    membership.is_muted = not membership.is_muted
    repo.commit()
    return {"is_muted": membership.is_muted}


def toggle_favorite(repo: IGroupsRepository, group_id: UUID, user_id: UUID) -> dict:
    membership = _get_membership(repo, group_id, user_id)
    if not membership:
        raise GroupMemberNotFoundError("Not a member of this group")

    membership.is_favorite = not membership.is_favorite
    repo.commit()
    return {"is_favorite": membership.is_favorite}


# ---------------------------------------------------------------------------
# Invite link
# ---------------------------------------------------------------------------

def get_or_create_invite_link(
    repo: IGroupsRepository, group_id: UUID, user_id: UUID, base_url: str = "https://api.vanijyaa.com"
) -> InviteLinkOut:
    _require_member(repo, group_id, user_id)
    group = _get_group_or_raise(repo, group_id)

    if not group.invite_link_token:
        group.invite_link_token = secrets.token_urlsafe(16)
        repo.commit()
        repo.refresh(group)

    return InviteLinkOut(
        invite_link_token=group.invite_link_token,
        join_url=f"{base_url}/api/v1/groups/join-by-link/{group.invite_link_token}",
    )


def join_by_invite_link(repo: IGroupsRepository, token: str, user_id: UUID) -> dict:
    group = repo.get_group_by_invite_token(token)
    if not group:
        raise GroupNotFoundError("Invalid or expired invite link")

    existing = _get_membership(repo, group.id, user_id)
    if existing:
        raise GroupAlreadyMemberError("Already a member of this group")

    try:
        repo.add(GroupMember(group_id=group.id, user_id=user_id, role="member"))
        group.member_count += 1
        repo.commit()
    except Exception:
        repo.rollback()
        raise

    return {
        "group_id": str(group.id),
        "group_name": group.name,
        "role": "member",
        "joined_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Join request management (private groups)
# ---------------------------------------------------------------------------

def get_join_requests(
    repo: IGroupsRepository,
    group_id: UUID,
    user_id: UUID,
    status: Optional[str] = "pending",
    page: int = 1,
    limit: int = 20,
) -> GroupJoinRequestListOut:
    _require_admin(repo, group_id, user_id)
    _get_group_or_raise(repo, group_id)

    requests, total = repo.list_join_requests(group_id, status, page, limit)

    return GroupJoinRequestListOut(
        requests=[GroupJoinRequestOut.model_validate(r) for r in requests],
        total=total,
        page=page,
        limit=limit,
    )


def resolve_join_request(
    repo: IGroupsRepository,
    group_id: UUID,
    request_id: UUID,
    admin_id: UUID,
    action: str,  # "approve" | "reject"
) -> dict:
    _require_admin(repo, group_id, admin_id)
    group = _get_group_or_raise(repo, group_id)

    req = (
        repo.get_join_request(group_id, request_id)
    )
    if not req:
        raise GroupJoinRequestNotFoundError("Join request not found")
    if req.status != "pending":
        raise GroupJoinRequestAlreadyResolvedError(f"Request already {req.status}")

    req.status = "approved" if action == "approve" else "rejected"
    req.resolved_at = datetime.now(timezone.utc)
    req.resolved_by = admin_id

    if action == "approve":
        existing = _get_membership(repo, group_id, req.user_id)
        if not existing:
            repo.add(GroupMember(group_id=group_id, user_id=req.user_id, role="member"))
            group.member_count += 1

    try:
        repo.commit()
    except Exception:
        repo.rollback()
        raise

    return {"request_id": str(request_id), "status": req.status}


def get_my_admin_pending_requests(
    repo: IGroupsRepository,
    user_id: UUID,
    page: int = 1,
    limit: int = 20,
):
    """
    Returns all pending join requests across every group the caller admins.
    Scoped entirely to user_id from JWT — no other user's data is ever returned.
    """
    from app.modules.groups.application.schemas import AdminPendingRequestOut, AdminPendingRequestsListOut

    admin_group_ids = list(repo.admin_group_ids(user_id))

    if not admin_group_ids:
        return AdminPendingRequestsListOut(requests=[], total=0, page=page, limit=limit)

    rows, total = repo.list_admin_pending_requests(admin_group_ids, page, limit)

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
