"""
Safety module — block and report endpoints.

The acting user is always derived from the JWT (get_current_user_id) — never
from a path or query parameter.

URL convention:
  {target_id} — the user being blocked / reported
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_current_user_id
from app.modules.safety.application import service
from app.modules.safety.domain.exceptions import (
    AlreadyBlockedError,
    BlockNotFoundError,
    BlockSelfError,
    DuplicateReportError,
    SelfReportError,
)
from app.modules.safety.domain.interfaces.repository import ISafetyRepository
from app.modules.safety.presentation.dependencies import get_safety_repo
from app.modules.safety.presentation.schemas import ReportRequest

router = APIRouter(prefix="/safety", tags=["safety"])


# ── Block ─────────────────────────────────────────────────────────────────────

@router.post("/block/{target_id}")
def block(
    target_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    repo: ISafetyRepository = Depends(get_safety_repo),
):
    """Block target_id as the authenticated user. Returns 409 if already blocked."""
    try:
        return service.block_user(repo, blocker_id=user_id, blocked_id=target_id)
    except BlockSelfError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AlreadyBlockedError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.delete("/block/{target_id}")
def unblock(
    target_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    repo: ISafetyRepository = Depends(get_safety_repo),
):
    """Remove a block. Returns 404 if no block exists."""
    try:
        return service.unblock_user(repo, blocker_id=user_id, blocked_id=target_id)
    except BlockNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/blocked")
def list_blocked(
    user_id: UUID = Depends(get_current_user_id),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    repo: ISafetyRepository = Depends(get_safety_repo),
):
    """Users the authenticated user has blocked, newest first."""
    return service.list_blocked(repo, blocker_id=user_id, page=page, limit=limit)


@router.get("/block/status/{target_id}")
def check_block_status(
    target_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    repo: ISafetyRepository = Depends(get_safety_repo),
):
    """Has the authenticated user blocked target_id? Drives block/unblock button state."""
    return service.block_status(repo, blocker_id=user_id, blocked_id=target_id)


# ── Report ────────────────────────────────────────────────────────────────────

@router.post("/report")
def report(
    payload: ReportRequest,
    user_id: UUID = Depends(get_current_user_id),
    repo: ISafetyRepository = Depends(get_safety_repo),
):
    """
    Submit a report for a user, group, or post.
    Returns 409 if you've already reported this target.
    """
    try:
        return service.submit_report(
            repo,
            reporter_id=user_id,
            target_type=payload.target_type,
            target_id=payload.target_id,
            reason=payload.reason,
            description=payload.description,
        )
    except SelfReportError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except DuplicateReportError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/reports")
def my_reports(
    user_id: UUID = Depends(get_current_user_id),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    repo: ISafetyRepository = Depends(get_safety_repo),
):
    """All reports submitted by the authenticated user, newest first."""
    return service.list_my_reports(repo, reporter_id=user_id, page=page, limit=limit)
