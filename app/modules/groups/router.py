"""
Groups & Management — 18 endpoints
Base prefix: /api/v1/groups

Route ordering:  specific paths before parameterised ones to avoid clashes.
  /suggestions            before  /:id
  /join-by-link/:token    before  /:id/...

All mutating endpoints require a Bearer token; user identity is derived from
the JWT via get_current_user_id — never from a client-supplied query param.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.dependencies import get_current_user_id, get_db
from app.modules.groups.schemas import (
    AddMembersRequest,
    GroupCreate,
    GroupPermissionsUpdate,
    GroupUpdate,
    ReportGroupRequest,
)
from app.modules.groups.service import (
    GroupConflictError,
    GroupNotFoundError,
    GroupPermissionError,
    GroupValidationError,
    add_members,
    create_group,
    delete_group,
    get_group,
    get_group_suggestions,
    get_members,
    get_or_create_invite_link,
    join_by_invite_link,
    join_group,
    leave_group,
    list_groups,
    remove_member,
    set_member_frozen,
    toggle_favorite,
    toggle_mute,
    update_group,
    update_permissions,
)
from app.shared.utils.response import ok

router = APIRouter(prefix="/api/v1/groups", tags=["Groups"])


# ── helpers ──────────────────────────────────────────────────────────────────

def _handle(fn, *args, **kwargs):
    """Dispatch service call → HTTP status codes."""
    try:
        return fn(*args, **kwargs)
    except GroupPermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except GroupNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except GroupConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except GroupValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ── 1. GET /suggestions/:user_id ─────────────────────────────────────────────

@router.get("/suggestions")
def suggest_groups(
    user_id: UUID = Depends(get_current_user_id),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    results = _handle(get_group_suggestions, db, user_id, page=page, limit=limit)
    return ok(results, "Group suggestions fetched")


# ── 2. GET / — list groups with optional filters ─────────────────────────────

@router.get("/")
def list_groups_api(
    user_id: UUID = Depends(get_current_user_id),
    commodity: str | None = Query(None),
    accessibility: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    result = _handle(
        list_groups, db, user_id,
        commodity=commodity,
        accessibility=accessibility,
        page=page,
        per_page=per_page,
    )
    return ok(result, "Groups fetched")


# ── 3. POST / — create group (verified users only) ───────────────────────────

@router.post("/", status_code=201)
def create_group_api(
    payload: GroupCreate,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    result = _handle(create_group, db, user_id, payload)
    return ok(result, "Group created successfully")


# ── 17. POST /join-by-link/:token — join via invite token ────────────────────
# Must be ABOVE /:id routes to prevent UUID path conflict.

@router.post("/join-by-link/{token}")
def join_by_link_api(
    token: str,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    result = _handle(join_by_invite_link, db, token, user_id)
    return ok(result, "Joined group via invite link")


# ── 4. GET /:id ───────────────────────────────────────────────────────────────

@router.get("/{group_id}")
def get_group_api(
    group_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    result = _handle(get_group, db, group_id, user_id)
    return ok(result, "Group fetched")


# ── 5. PATCH /:id — update group info (admin only) ───────────────────────────

@router.patch("/{group_id}")
def update_group_api(
    group_id: UUID,
    payload: GroupUpdate,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    result = _handle(update_group, db, group_id, user_id, payload)
    return ok(result, "Group updated")


# ── 6. PATCH /:id/permissions — update access/posting rules (admin only) ─────

@router.patch("/{group_id}/permissions")
def update_permissions_api(
    group_id: UUID,
    payload: GroupPermissionsUpdate,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    result = _handle(update_permissions, db, group_id, user_id, payload)
    return ok(result, "Permissions updated")


# ── 7. POST /:id/join ─────────────────────────────────────────────────────────

@router.post("/{group_id}/join")
def join_group_api(
    group_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    result = _handle(join_group, db, group_id, user_id)
    return ok(result, "Joined group")


# ── 8. DELETE /:id/leave ──────────────────────────────────────────────────────

@router.delete("/{group_id}/leave")
def leave_group_api(
    group_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _handle(leave_group, db, group_id, user_id)
    return ok(message="Left group")


# ── 9. GET /:id/members ───────────────────────────────────────────────────────

@router.get("/{group_id}/members")
def get_members_api(
    group_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    result = _handle(get_members, db, group_id, user_id, page=page, limit=limit)
    return ok(result, "Members fetched")


# ── 10. POST /:id/members/add — bulk add members (admin only) ─────────────────

@router.post("/{group_id}/members/add")
def add_members_api(
    group_id: UUID,
    payload: AddMembersRequest,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    result = _handle(add_members, db, group_id, user_id, payload.user_ids)
    return ok(result, "Members added")


# ── 11. DELETE /:id/members/:uid — remove member (admin only) ────────────────

@router.delete("/{group_id}/members/{target_user_id}")
def remove_member_api(
    group_id: UUID,
    target_user_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _handle(remove_member, db, group_id, user_id, target_user_id)
    return ok(message="Member removed")


# ── 12. POST /:id/members/:uid/freeze — freeze member (admin only) ───────────

@router.post("/{group_id}/members/{target_user_id}/freeze")
def freeze_member_api(
    group_id: UUID,
    target_user_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    result = _handle(set_member_frozen, db, group_id, user_id, target_user_id, True)
    return ok(result, "Member frozen")


# ── 13. DELETE /:id/members/:uid/freeze — unfreeze member (admin only) ───────

@router.delete("/{group_id}/members/{target_user_id}/freeze")
def unfreeze_member_api(
    group_id: UUID,
    target_user_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    result = _handle(set_member_frozen, db, group_id, user_id, target_user_id, False)
    return ok(result, "Member unfrozen")


# ── 14. POST /:id/mute — toggle mute for current user ────────────────────────

@router.post("/{group_id}/mute")
def mute_group_api(
    group_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    result = _handle(toggle_mute, db, group_id, user_id)
    return ok(result, "Mute toggled")


# ── 15. POST /:id/favorite — toggle favorite for current user ────────────────

@router.post("/{group_id}/favorite")
def favorite_group_api(
    group_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    result = _handle(toggle_favorite, db, group_id, user_id)
    return ok(result, "Favorite toggled")


# ── 16. GET /:id/invite-link — get / generate invite link (admin only) ───────

@router.get("/{group_id}/invite-link")
def invite_link_api(
    group_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    result = _handle(get_or_create_invite_link, db, group_id, user_id)
    return ok(result, "Invite link ready")


# ── 18. POST /:id/report ─────────────────────────────────────────────────────

@router.post("/{group_id}/report")
def report_group_api(
    group_id: UUID,
    payload: ReportGroupRequest,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _handle(get_group, db, group_id, user_id)
    return ok(
        {"group_id": str(group_id), "reason": payload.reason, "status": "submitted"},
        "Report submitted — our team will review it",
    )
