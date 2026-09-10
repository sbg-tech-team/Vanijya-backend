"""
Safety module — block and report endpoints.

The acting user is always derived from the JWT (get_current_user_id) — never
from a path or query parameter.

URL convention:
  {target_id} — the user being blocked / reported
"""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_current_user_id, get_db
from app.modules.safety import service
from app.modules.safety.schemas import ReportRequest

router = APIRouter(prefix="/safety", tags=["safety"])


# ── Block ─────────────────────────────────────────────────────────────────────

@router.post("/block/{target_id}")
def block(
    target_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Block target_id as the authenticated user. Returns 409 if already blocked."""
    return service.block_user(db, blocker_id=user_id, blocked_id=target_id)


@router.delete("/block/{target_id}")
def unblock(
    target_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Remove a block. Returns 404 if no block exists."""
    return service.unblock_user(db, blocker_id=user_id, blocked_id=target_id)


@router.get("/blocked")
def list_blocked(
    user_id: UUID = Depends(get_current_user_id),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Users the authenticated user has blocked, newest first."""
    return service.list_blocked(db, blocker_id=user_id, page=page, limit=limit)


@router.get("/block/status/{target_id}")
def check_block_status(
    target_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Has the authenticated user blocked target_id? Drives block/unblock button state."""
    return service.block_status(db, blocker_id=user_id, blocked_id=target_id)


# ── Report ────────────────────────────────────────────────────────────────────

@router.post("/report")
def report(
    payload: ReportRequest,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Submit a report for a user, group, or post.
    Returns 409 if you've already reported this target.
    """
    return service.submit_report(db, reporter_id=user_id, payload=payload)


@router.get("/reports")
def my_reports(
    user_id: UUID = Depends(get_current_user_id),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """All reports submitted by the authenticated user, newest first."""
    return service.list_my_reports(db, reporter_id=user_id, page=page, limit=limit)
