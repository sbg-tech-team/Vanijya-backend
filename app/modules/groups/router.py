"""
Groups & Management — 21 endpoints
Base prefix: /api/v1/groups

Route ordering:  specific paths before parameterised ones to avoid clashes.
  /upload-image          before  /:id
  /suggestions           before  /:id
  /join-by-link/:token   before  /:id/...

All mutating endpoints require a Bearer token; user identity is derived from
the JWT via get_current_user_id — never from a client-supplied query param.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_current_user_id, get_db
from app.modules.groups.schemas import (
    AddMembersRequest,
    GroupCreate,
    GroupDealCreate,
    GroupDealPublishRequest,
    GroupDealUpdate,
    GroupPermissionsUpdate,
    GroupUpdate,
    ReportGroupRequest,
)
from app.modules.groups.service import (
    GroupConflictError,
    GroupNotFoundError,
    GroupPermissionError,
    GroupStorageError,
    GroupValidationError,
    add_members,
    close_group_deal,
    create_group,

    delete_group,
    delete_group_media,
    get_group,
    get_group_deal,
    get_group_image_upload_url,
    get_group_media_upload_url,
    get_group_suggestions,
    get_join_requests,
    get_members,
    get_my_admin_pending_requests,
    get_or_create_invite_link,
    join_by_invite_link,
    join_group,
    leave_group,
    list_group_deals,
    list_group_media,
    list_groups,
    publish_group_deal,
    remove_member,
    resolve_join_request,
    set_member_frozen,
    toggle_favorite,
    toggle_mute,
    update_group,
    update_group_deal,
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


# ── 0a. POST /upload-image — get signed URL for group cover image ─────────────
# Must be ABOVE /:id routes to prevent UUID path conflict.

@router.post("/upload-image")
async def group_image_upload_url_api(
    user_id: UUID = Depends(get_current_user_id),
    content_type: str = Query(..., description="image/jpeg | image/png | image/webp"),
):
    """
    Step 1 — get a signed upload URL for the group cover image.
    Step 2: PUT image bytes directly to upload_url (Content-Type must match).
    Step 3: pass image_url in GroupCreate.image_url when creating the group.
    """
    try:
        result = await get_group_image_upload_url(user_id, content_type)
        return ok(result, "Group image upload URL generated")
    except GroupValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except GroupStorageError as e:
        raise HTTPException(status_code=503, detail=str(e))


# ── 1. GET /suggestions ───────────────────────────────────────────────────────

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
    commodity: str | None = Query(None, description="Filter by commodity (e.g. sugar, rice)"),
    accessibility: str | None = Query(None, description="public | private | invite_only"),
    search: str | None = Query(None, description="Search by group name"),
    region_market: str | None = Query(None, description="Filter by market/region name"),
    target_role: str | None = Query(None, description="Filter by target role (trader | broker | exporter)"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    result = _handle(
        list_groups, db, user_id,
        commodity=commodity,
        accessibility=accessibility,
        search=search,
        region_market=region_market,
        target_role=target_role,
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


# ── GET /my-pending-requests — all pending join requests across admin's groups ─
# Must be ABOVE /:id routes to prevent UUID path conflict.

@router.get("/my-pending-requests")
def my_pending_requests_api(
    user_id: UUID = Depends(get_current_user_id),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    result = _handle(get_my_admin_pending_requests, db, user_id, page=page, limit=limit)
    return ok(result, "Pending join requests fetched")


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


# ── 5. PATCH /:id — update g/roup info (admin only) ───────────────────────────

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


# ── 19. POST /:id/media/upload — get signed URL for group media ───────────────

@router.post("/{group_id}/media/upload")
async def group_media_upload_url_api(
    group_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    content_type: str = Query(
        ...,
        description="image/jpeg | image/png | image/webp | video/mp4 | video/quicktime | video/webm",
    ),
    db: Session = Depends(get_db),
):
    """
    Step 1 — get a signed upload URL for a group media file.
    Creates the GroupMedia DB record immediately and returns media_id.
    Step 2: PUT bytes directly to upload_url (Content-Type must match).
    """
    try:
        result = await get_group_media_upload_url(db, group_id, user_id, content_type)
        return ok(result, "Group media upload URL generated")
    except GroupPermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except GroupNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except GroupValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except GroupStorageError as e:
        raise HTTPException(status_code=503, detail=str(e))


# ── 20. GET /:id/media — list media for a group ───────────────────────────────

@router.get("/{group_id}/media")
def list_group_media_api(
    group_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    result = _handle(list_group_media, db, group_id, user_id, page=page, limit=limit)
    return ok(result, "Group media fetched")


# ── 21. DELETE /:id/media/:media_id — delete a media item ────────────────────

@router.delete("/{group_id}/media/{media_id}")
async def delete_group_media_api(
    group_id: UUID,
    media_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        await delete_group_media(db, group_id, media_id, user_id)
    except GroupPermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except GroupNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ok(message="Media deleted")


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


# ── Group Deals ──────────────────────────────────────────────────────────────

@router.get("/{group_id}/deals")
def list_deals_api(
    group_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    result = _handle(list_group_deals, db, group_id, user_id, page=page, limit=limit)
    return ok(result, "Deals fetched")


@router.get("/{group_id}/deals/{deal_id}")
def get_deal_api(
    group_id: UUID,
    deal_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    result = _handle(get_group_deal, db, group_id, deal_id, user_id)
    return ok(result, "Deal fetched")


@router.patch("/{group_id}/deals/{deal_id}")
def update_deal_api(
    group_id: UUID,
    deal_id: UUID,
    payload: GroupDealUpdate,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    result = _handle(update_group_deal, db, group_id, deal_id, user_id, payload)
    return ok(result, "Deal updated")


@router.post("/{group_id}/deals/{deal_id}/close")
def close_deal_api(
    group_id: UUID,
    deal_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    result = _handle(close_group_deal, db, group_id, deal_id, user_id)
    return ok(result, "Deal closed status toggled")


@router.post("/{group_id}/deals/{deal_id}/publish")
def publish_deal_api(
    group_id: UUID,
    deal_id: UUID,
    payload: GroupDealPublishRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = _handle(
        publish_group_deal,
        db, group_id, deal_id, current_user.user_id, current_user.profile_id, payload.is_public,
    )
    return ok(result, "Deal published to feed")


# ── Join requests (private groups) ───────────────────────────────────────────

# ── GET /:id/join-requests — admin views pending/all requests ─────────────────

@router.get("/{group_id}/join-requests")
def list_join_requests_api(
    group_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    status: str | None = Query("pending", description="pending | approved | rejected"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    result = _handle(get_join_requests, db, group_id, user_id, status=status, page=page, limit=limit)
    return ok(result, "Join requests fetched")


# ── POST /:id/join-requests/:request_id/approve ───────────────────────────────

@router.post("/{group_id}/join-requests/{request_id}/approve")
def approve_join_request_api(
    group_id: UUID,
    request_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    result = _handle(resolve_join_request, db, group_id, request_id, user_id, "approve")
    return ok(result, "Join request approved")


# ── POST /:id/join-requests/:request_id/reject ────────────────────────────────

@router.post("/{group_id}/join-requests/{request_id}/reject")
def reject_join_request_api(
    group_id: UUID,
    request_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    result = _handle(resolve_join_request, db, group_id, request_id, user_id, "reject")
    return ok(result, "Join request rejected")
