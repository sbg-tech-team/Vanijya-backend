"""Call liveness ping.

The client calls this every HEARTBEAT_INTERVAL_SECONDS while it is in a call.
When the pings stop, every client is gone — force-quit, crashed, or out of
battery — and the heartbeat sweeper tears the call down.

This is the only signal that distinguishes "still talking" from "app is dead".
Without it the sole evidence a call is over is the client politely saying so,
which is exactly what fails in the cases that cost money.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import redis as redis_lib

from app.modules.calling.application import presence
from app.modules.calling.application.schemas import CallHeartbeatOut
from app.modules.calling.domain.exceptions import (
    CallAlreadyEndedError,
    CallNotFoundError,
    NotParticipantError,
)
from app.modules.calling.domain.interfaces.repository import ICallingRepository
from app.modules.calling.domain.value_objects import HEARTBEAT_INTERVAL_SECONDS


def heartbeat(
    repo: ICallingRepository,
    *,
    call_id: UUID,
    user_id: UUID,
    rc: "redis_lib.Redis | None" = None,
) -> CallHeartbeatOut:
    call = repo.get_call(call_id)
    if call is None:
        raise CallNotFoundError("Call not found.")
    if call.participant(user_id) is None:
        raise NotParticipantError("You are not a participant in this call.")
    if call.is_terminal():
        # Tells a client whose socket and push both missed the teardown that the
        # call is over, so it can stop the media session instead of billing on.
        raise CallAlreadyEndedError("Call has already ended.")

    now = datetime.now(timezone.utc)
    # Redis is the fast path — a write per participant per 30 s is a lot of row
    # churn for data that lives ninety seconds. Fall back to the column only
    # when Redis refuses, so presence never silently stops being recorded.
    if not presence.touch(rc, call_id, user_id):
        repo.touch_heartbeat(call_id, user_id, now)
        repo.commit()
    return CallHeartbeatOut(
        call_id=call_id,
        status=call.status,
        next_heartbeat_in_seconds=HEARTBEAT_INTERVAL_SECONDS,
    )
