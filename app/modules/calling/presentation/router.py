"""Calling module — HTTP layer (thin wrappers only, zero business logic).

Identity always comes from the Bearer token, never from a path or body.

Side effects (Socket.IO emits, FCM pushes) are described by the use cases as a
CallDispatch and fired here through BackgroundTasks — the same pattern the post,
chat and connections routers use, so the response returns before any push I/O.
"""
from __future__ import annotations

import logging

from uuid import UUID

import redis as redis_lib
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from app.core.monitoring import set_call_context
from app.core.rate_limiter import rate_limiter
from app.core.redis_client import get_redis
from app.dependencies import get_current_user_id
from app.modules.calling.application.budget import current_usage
from app.modules.calling.application.dispatch import CallDispatch
from app.modules.calling.application.use_cases import service
from app.modules.calling.domain.exceptions import (
    CallAlreadyEndedError,
    CallBlockedError,
    CallBudgetExceededError,
    CalleeBusyError,
    CallerBusyError,
    CallFullError,
    CallingError,
    CallNotFoundError,
    CallNotRingingError,
    CallTargetNotFoundError,
    NotGroupMemberError,
    NotParticipantError,
    SelfCallError,
    VideoNotAvailableError,
    VideoProviderError,
)
from app.modules.calling.domain.interfaces.repository import ICallingRepository
from app.modules.calling.domain.interfaces.video_provider import IVideoProvider
from app.modules.calling.domain.value_objects import (
    INITIATE_RATE_LIMIT,
    INITIATE_RATE_WINDOW_SECONDS,
)
from app.modules.calling.presentation.dependencies import (
    get_calling_repo,
    get_video_provider,
    push_task,
)
from app.modules.calling.presentation.schemas import (
    CallCreate,
    DeviceRegister,
    CallEndedOut,
    CallHistoryOut,
    CallOut,
    CallRejectedOut,
    CallTokenOut,
)
from app.shared.utils.response import ok

log = logging.getLogger(__name__)

router = APIRouter(prefix="/calls", tags=["Calling"])


# ── Error mapping ─────────────────────────────────────────────────────────────

_STATUS_BY_EXC: dict[type[CallingError], int] = {
    SelfCallError:           400,
    CallBlockedError:        403,
    NotGroupMemberError:     403,
    NotParticipantError:     403,
    CallNotFoundError:       404,
    CallTargetNotFoundError: 404,
    CallerBusyError:         409,
    CalleeBusyError:         409,
    CallNotRingingError:     409,
    CallAlreadyEndedError:   409,
    CallFullError:           409,
    CallBudgetExceededError: 429,
    VideoNotAvailableError:  501,
    VideoProviderError:      503,
}


def _translate(exc: CallingError) -> HTTPException:
    status = _STATUS_BY_EXC.get(type(exc), 500)
    return HTTPException(status_code=status, detail=str(exc) or "Call error")


def _dispatch(background: BackgroundTasks, result: CallDispatch):
    """Queue the socket emits and pushes a use case asked for."""
    from app.core.realtime import emit_to_group, emit_to_user

    for ev in result.socket_events:
        if ev.group_id is not None:
            background.add_task(emit_to_group, ev.group_id, ev.event, ev.payload)
        elif ev.user_id is not None:
            background.add_task(emit_to_user, ev.user_id, ev.event, ev.payload)

    for msg in result.pushes:
        # A group call's push is a group notification; everything else rides
        # the master switch only.
        category = "group" if msg.data.get("call_type") == "group" else "push"
        background.add_task(push_task, msg.user_ids, msg.data, category)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("", response_model=None, status_code=201)
def create_call(
    payload: CallCreate,
    background_tasks: BackgroundTasks,
    me: UUID = Depends(get_current_user_id),
    repo: ICallingRepository = Depends(get_calling_repo),
    provider: IVideoProvider = Depends(get_video_provider),
    r: redis_lib.Redis = Depends(get_redis),
):
    """Start a call. Any user may call any other user; the only gates are blocks,
    group membership, and both parties being free.

    Rate limited because there is no relationship requirement — without it a new
    account could cold-call the whole platform.
    """
    try:
        rate_limiter.check(
            r, f"calls:initiate:{me}",
            limit=INITIATE_RATE_LIMIT, window=INITIATE_RATE_WINDOW_SECONDS,
        )
    except HTTPException:
        raise
    except Exception:
        # Redis down must not block calling; the limiter is a guard, not a gate.
        log.warning("call-initiate rate limiting unavailable for %s", me)

    try:
        result = service.initiate_call(
            repo, provider,
            caller_id=me,
            call_type=payload.call_type,
            target_user_id=payload.target_user_id,
            group_id=payload.group_id,
            media=payload.media,
            rc=r,
        )
    except CallingError as exc:
        raise _translate(exc) from exc

    set_call_context(result.result.call_id, call_type=payload.call_type,
                     status=result.result.status, caller=str(me))
    _dispatch(background_tasks, result)
    return ok(result.result.model_dump(mode="json"), "Call initiated")


@router.post("/{call_id}/accept", response_model=None)
def accept_call(
    call_id: UUID,
    background_tasks: BackgroundTasks,
    me: UUID = Depends(get_current_user_id),
    repo: ICallingRepository = Depends(get_calling_repo),
    provider: IVideoProvider = Depends(get_video_provider),
):
    """Answer a ringing call. Returns the Stream token to join with."""
    try:
        result = service.accept_call(repo, provider, call_id=call_id, user_id=me)
    except CallingError as exc:
        raise _translate(exc) from exc

    set_call_context(call_id, status=result.result.status, actor=str(me))
    _dispatch(background_tasks, result)
    return ok(result.result.model_dump(mode="json"), "Call accepted")


@router.post("/{call_id}/reject", response_model=None)
def reject_call(
    call_id: UUID,
    background_tasks: BackgroundTasks,
    me: UUID = Depends(get_current_user_id),
    repo: ICallingRepository = Depends(get_calling_repo),
    provider: IVideoProvider = Depends(get_video_provider),
):
    """Decline a ringing call. 1:1 ends it; in a group only you drop out."""
    try:
        result = service.reject_call(repo, call_id=call_id, user_id=me, provider=provider)
    except CallingError as exc:
        raise _translate(exc) from exc

    set_call_context(call_id, status=result.result.status, actor=str(me))
    _dispatch(background_tasks, result)
    return ok(result.result.model_dump(mode="json"), "Call rejected")


@router.post("/{call_id}/end", response_model=None)
def end_call(
    call_id: UUID,
    background_tasks: BackgroundTasks,
    me: UUID = Depends(get_current_user_id),
    repo: ICallingRepository = Depends(get_calling_repo),
    provider: IVideoProvider = Depends(get_video_provider),
    r: redis_lib.Redis = Depends(get_redis),
):
    """Hang up. Duration is computed server-side from started_at — a
    client-reported duration is never trusted.

    Terminates the session on Stream as well as in our database: ending it only
    locally would leave the media session, and the billing, running."""
    try:
        result = service.end_call(
            repo, call_id=call_id, user_id=me, provider=provider, rc=r,
        )
    except CallingError as exc:
        raise _translate(exc) from exc

    set_call_context(call_id, status=result.result.status, actor=str(me))
    _dispatch(background_tasks, result)
    return ok(result.result.model_dump(mode="json"), "Call ended")


@router.post("/{call_id}/heartbeat", response_model=None)
def call_heartbeat(
    call_id: UUID,
    me: UUID = Depends(get_current_user_id),
    repo: ICallingRepository = Depends(get_calling_repo),
    r: redis_lib.Redis = Depends(get_redis),
):
    """Liveness ping. Send every 30 s while in a call.

    When the pings stop the backend knows every client is gone — force-quit,
    crashed, or out of battery — and tears the call down. Without it the only
    evidence a call is over is the client politely saying so, which is exactly
    what fails in the cases that cost money.

    A 409 means the call is already over: stop the media session immediately.
    """
    try:
        result = service.heartbeat(repo, call_id=call_id, user_id=me, rc=r)
    except CallingError as exc:
        raise _translate(exc) from exc
    return ok(result.model_dump(mode="json"), "Heartbeat recorded")


@router.post("/{call_id}/token", response_model=None)
def refresh_call_token(
    call_id: UUID,
    me: UUID = Depends(get_current_user_id),
    repo: ICallingRepository = Depends(get_calling_repo),
    provider: IVideoProvider = Depends(get_video_provider),
):
    """Re-mint the Stream token for a call in progress. Tokens last one hour;
    refresh before expiry on long calls."""
    try:
        result = service.refresh_token(repo, provider, call_id=call_id, user_id=me)
    except CallingError as exc:
        raise _translate(exc) from exc
    return ok(result.model_dump(mode="json"), "Token refreshed")


@router.get("/usage", response_model=None)
def call_usage(
    me: UUID = Depends(get_current_user_id),
    r: redis_lib.Redis = Depends(get_redis),
):
    """Current participant-minute burn against the budgets.

    Registered BEFORE /{call_id} so "usage" is not parsed as a call id.

    No role gate, matching the rest of this codebase (the news admin routes are
    authenticated-only too). Users see their own daily figure; the platform
    totals are included because without them there is no way to see a budget
    breach coming except by grepping logs.
    """
    return ok(current_usage(r, me), "Call usage fetched")


@router.post("/devices", response_model=None, status_code=201)
def register_device(
    body: DeviceRegister,
    me: UUID = Depends(get_current_user_id),
    repo: ICallingRepository = Depends(get_calling_repo),
):
    """Register this device's FCM token so it rings.

    Call on every sign-in and on every FCM token refresh. Registering a token
    that already exists moves it to the calling user — a handset handed over
    must not keep ringing the previous owner.

    Registered BEFORE /{call_id} so "devices" is not parsed as a call id.
    """
    result = service.register_device(
        repo, user_id=me, fcm_token=body.fcm_token, platform=body.platform,
        token_type=body.token_type,
    )
    return ok(result.model_dump(mode="json"), "Device registered")


@router.get("", response_model=None)
def list_calls(
    me: UUID = Depends(get_current_user_id),
    repo: ICallingRepository = Depends(get_calling_repo),
    limit: int = Query(20, ge=1, le=50),
    cursor: str | None = Query(None, description="Opaque cursor from next_cursor"),
    call_type: str | None = Query(None, pattern="^(dm|group)$"),
):
    """Call history, newest first."""
    result = service.list_calls(
        repo, user_id=me, limit=limit, cursor=cursor, call_type=call_type,
    )
    return ok(result.model_dump(mode="json"), "Call history fetched")


@router.get("/{call_id}", response_model=None)
def get_call(
    call_id: UUID,
    me: UUID = Depends(get_current_user_id),
    repo: ICallingRepository = Depends(get_calling_repo),
):
    """Current state of one call. Use on app resume or after a missed socket
    event — not for polling in a loop. No Stream token is issued here."""
    try:
        result = service.get_call(repo, call_id=call_id, user_id=me)
    except CallingError as exc:
        raise _translate(exc) from exc
    return ok(result.model_dump(mode="json"), "Call fetched")
