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
from app.modules.calling.domain.value_objects import (
    HEARTBEAT_INTERVAL_SECONDS,
    TERMINAL_STATUSES,
)


def heartbeat(
    repo: ICallingRepository,
    *,
    call_id: UUID,
    user_id: UUID,
    rc: "redis_lib.Redis | None" = None,
) -> CallHeartbeatOut:
    # get_call_heartbeat_state, not get_call: this is the highest-frequency
    # call in the module (every ~30s per participant), and all it needs is
    # status + participant existence — get_call()'s full rebuild also joins
    # every participant's name/avatar, which heartbeat never reads.
    state = repo.get_call_heartbeat_state(call_id, user_id)
    if state is None:
        raise CallNotFoundError("Call not found.")
    status, is_participant = state
    if not is_participant:
        raise NotParticipantError("You are not a participant in this call.")
    if status in TERMINAL_STATUSES:
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
        status=status,
        next_heartbeat_in_seconds=HEARTBEAT_INTERVAL_SECONDS,
    )
