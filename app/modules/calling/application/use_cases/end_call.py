"""Hang up, plus the chat call-card write.

1:1 — either side ending terminates the call.
Group — you leave; the call ends only when the last joined participant goes.

Duration is computed by the repository from started_at -> now. We never trust a
client-reported duration.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

import redis as redis_lib

from app.modules.calling.application.budget import record_usage
from app.modules.calling.application.dispatch import CallDispatch, PushMessage, SocketEvent
from app.modules.calling.application.schemas import CallEndedOut
from app.modules.calling.domain.interfaces.video_provider import IVideoProvider
from app.modules.calling.domain.entities import CallEntity
from app.modules.calling.domain.exceptions import (
    CallAlreadyEndedError,
    CallNotFoundError,
    NotParticipantError,
)
from app.modules.calling.domain.interfaces.repository import ICallingRepository
from app.modules.calling.domain.value_objects import (
    CallStatus,
    CallType,
    EndReason,
)

log = logging.getLogger(__name__)


def end_call(
    repo: ICallingRepository,
    *,
    call_id: UUID,
    user_id: UUID,
    provider: IVideoProvider | None = None,
    rc: "redis_lib.Redis | None" = None,
) -> CallDispatch:
    # Lock first, then read: serialises the whole end path per call so the last
    # two participants hanging up at the same instant cannot both observe the
    # other as still present and leave the call running.
    if not repo.lock_call(call_id):
        raise CallNotFoundError("Call not found.")

    call = repo.get_call(call_id)
    if call is None:
        raise CallNotFoundError("Call not found.")

    if call.participant(user_id) is None:
        raise NotParticipantError("You are not a participant in this call.")

    if call.is_terminal():
        raise CallAlreadyEndedError("Call has already ended.")

    now = datetime.now(timezone.utc)
    was_answered = call.status == CallStatus.ACTIVE.value

    try:
        repo.mark_participant_left(call_id, user_id, now)

        # Group calls survive one person leaving, unless they were the last in.
        if call.call_type == CallType.GROUP.value:
            if repo.active_participant_count(call_id) > 0:
                repo.commit()
                return CallDispatch(
                    result=CallEndedOut(
                        call_id=call_id,
                        status=CallStatus.ACTIVE.value,
                        started_at=call.started_at,
                        ended_at=None,
                        duration_seconds=0,
                        end_reason=None,
                    ),
                    socket_events=[SocketEvent(
                        event="call_participant_left",
                        payload={"call_id": str(call_id), "user_id": str(user_id)},
                        group_id=call.context_id,
                    )],
                )

        # Caller hanging up on an unanswered call is a cancel, not a hang-up.
        if was_answered:
            status, reason = CallStatus.ENDED.value, EndReason.HUNG_UP.value
        elif user_id == call.initiator_id:
            status, reason = CallStatus.CANCELLED.value, EndReason.CANCELLED.value
        else:
            status, reason = CallStatus.ENDED.value, EndReason.HUNG_UP.value

        # Tell the provider BEFORE our own write: this is what actually stops
        # the billing. If the DB write then fails we have lost a history row,
        # whereas the reverse would leave a session running that our records
        # claim is over.
        if provider is not None and provider.end_call_remote(
            call.stream_call_type, call.stream_call_id
        ):
            # Recorded so the retry sweep can spot the ones that did NOT succeed.
            repo.mark_provider_ended(call_id, now)

        ended = repo.end_call(call_id, status, reason, now)
        _write_call_card(repo, ended)
        repo.commit()
    except Exception:
        repo.rollback()
        raise

    # Bill the finished call against the per-user and platform budgets.
    if ended.duration_seconds > 0:
        record_usage(rc, [p.user_id for p in ended.participants], ended.duration_seconds)

    other_ids = [p.user_id for p in call.participants if p.user_id != user_id]
    payload = {
        "call_id": str(call_id),
        "ended_by": str(user_id),
        "ended_at": ended.ended_at.isoformat() if ended.ended_at else None,
        "duration_seconds": ended.duration_seconds,
        "end_reason": ended.end_reason,
    }

    events: list[SocketEvent] = []
    if call.call_type == CallType.GROUP.value:
        events.append(SocketEvent(event="call_ended", payload=payload, group_id=call.context_id))
    else:
        events.extend(
            SocketEvent(event="call_ended", payload=payload, user_id=uid) for uid in other_ids
        )

    pushes: list[PushMessage] = []
    if other_ids:
        # Always push, answered or not. If the peer is backgrounded their socket
        # may be gone, and without this their client keeps the media session
        # open — still billing — because nothing told it the call was over.
        # Unanswered: dismiss the incoming-call screen. Answered: tear down.
        pushes.append(PushMessage(
            user_ids=other_ids,
            data={
                "type": "call_ended" if was_answered else "call_cancelled",
                "call_id": str(call_id),
                "end_reason": ended.end_reason or EndReason.CANCELLED.value,
                "duration_seconds": str(ended.duration_seconds),
            },
        ))

    return CallDispatch(
        result=CallEndedOut(
            call_id=call_id,
            status=ended.status,
            started_at=ended.started_at,
            ended_at=ended.ended_at,
            duration_seconds=ended.duration_seconds,
            end_reason=ended.end_reason,
        ),
        socket_events=events,
        pushes=pushes,
    )


# ── Chat call card ────────────────────────────────────────────────────────────

def _write_call_card(repo: ICallingRepository, call: CallEntity) -> None:
    """Record the finished call as a chat message so it renders inline in the
    thread, WhatsApp-style. Group calls post into the group thread."""
    repo.write_call_card(
        context_type="group" if call.call_type == CallType.GROUP.value else "dm",
        context_id=call.context_id,
        sender_id=call.initiator_id,
        call_id=call.id,
        media=call.media,
        status=call.status,
        end_reason=call.end_reason,
        duration_seconds=call.duration_seconds,
        sent_at=call.ended_at or datetime.now(timezone.utc),
    )
