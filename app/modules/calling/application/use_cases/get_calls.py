"""Read paths: single call state, history, and Stream token refresh."""
from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime, timezone
from uuid import UUID

from app.modules.calling.application.presenters import to_call_out, to_history_item
from app.modules.calling.application.schemas import (
    CallHistoryOut,
    CallOut,
    CallTokenOut,
)
from app.modules.calling.domain.exceptions import (
    CallAlreadyEndedError,
    CallNotFoundError,
    CallNotRingingError,
    NotParticipantError,
    VideoProviderError,
)
from app.modules.calling.domain.interfaces.repository import ICallingRepository
from app.modules.calling.domain.interfaces.video_provider import IVideoProvider
from app.modules.calling.domain.value_objects import (
    MAX_CALL_DURATION_SECONDS,
    RING_TIMEOUT_SECONDS,
    CallStatus,
    ParticipantState,
)


def get_call(
    repo: ICallingRepository, *, call_id: UUID, user_id: UUID
) -> CallOut:
    call = repo.get_call(call_id)
    if call is None:
        raise CallNotFoundError("Call not found.")
    if call.participant(user_id) is None:
        # Don't leak the existence of calls the caller isn't in.
        raise CallNotFoundError("Call not found.")

    ring_timeout = (
        RING_TIMEOUT_SECONDS if call.status == CallStatus.RINGING.value else None
    )
    return to_call_out(call, ring_timeout=ring_timeout)


def list_calls(
    repo: ICallingRepository,
    *,
    user_id: UUID,
    limit: int = 20,
    cursor: str | None = None,
    call_type: str | None = None,
) -> CallHistoryOut:
    items, next_created_at = repo.list_calls(
        user_id=user_id,
        limit=limit,
        cursor=_decode_cursor(cursor),
        call_type=call_type,
    )
    return CallHistoryOut(
        calls=[to_history_item(i) for i in items],
        next_cursor=_encode_cursor(next_created_at),
    )


def refresh_token(
    repo: ICallingRepository,
    provider: IVideoProvider,
    *,
    call_id: UUID,
    user_id: UUID,
) -> CallTokenOut:
    call = repo.get_call(call_id)
    if call is None:
        raise CallNotFoundError("Call not found.")
    me = call.participant(user_id)
    if me is None:
        raise NotParticipantError("You are not a participant in this call.")
    # Only someone already in the call may re-mint a token. Without this a
    # RINGING callee could mint one here and join the media session directly,
    # skipping /accept entirely — the call would stay `ringing`, never get a
    # started_at, and be swept as missed 45 s later while they were mid-
    # conversation. It would also bill for those seconds.
    if me.state != ParticipantState.JOINED.value:
        raise CallNotRingingError("Accept the call before requesting a token.")
    if call.is_terminal():
        raise CallAlreadyEndedError("Call has already ended.")
    # Refusing past the cap stops a client renewing its way around the hard
    # duration limit and billing indefinitely.
    if call.started_at is not None:
        started = call.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - started).total_seconds()
        if age >= MAX_CALL_DURATION_SECONDS:
            raise CallAlreadyEndedError("Call has reached its maximum duration.")
    if not provider.is_configured:
        raise VideoProviderError("Calling is temporarily unavailable.")

    try:
        creds = provider.issue_token(user_id, call.stream_call_type, call.stream_call_id)
    except Exception as exc:
        raise VideoProviderError("Calling is temporarily unavailable.") from exc

    return CallTokenOut(token=creds.token, expires_at=creds.expires_at)


# ── Cursor ────────────────────────────────────────────────────────────────────
# Opaque to the client so the underlying ordering column can change later
# without breaking saved cursors.

def _encode_cursor(created_at: datetime | None) -> str | None:
    if created_at is None:
        return None
    raw = json.dumps({"created_at": created_at.isoformat()}).encode()
    return base64.urlsafe_b64encode(raw).decode()


def _decode_cursor(cursor: str | None) -> datetime | None:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode())
        return datetime.fromisoformat(json.loads(raw)["created_at"])
    except (ValueError, KeyError, TypeError, binascii.Error, json.JSONDecodeError):
        # A malformed cursor reads as "start from the beginning" rather than 400 —
        # a stale saved cursor should not break the history screen.
        return None
