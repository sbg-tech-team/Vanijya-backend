"""Accept or reject a ringing call.

1:1 reject ends the call for both sides. Group reject only removes you — the
call continues for everyone else.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from app.modules.calling.application.dispatch import CallDispatch, PushMessage, SocketEvent
from app.modules.calling.application.presenters import to_call_out
from app.modules.calling.application.schemas import CallRejectedOut
from app.modules.calling.domain.exceptions import (
    CallBlockedError,
    CallFullError,
    CallNotFoundError,
    CallNotRingingError,
    NotParticipantError,
    VideoProviderError,
)
from app.modules.calling.domain.interfaces.repository import ICallingRepository
from app.modules.calling.domain.interfaces.video_provider import IVideoProvider
from app.modules.calling.domain.value_objects import (
    MAX_CALL_PARTICIPANTS,
    CallStatus,
    CallType,
    EndReason,
    ParticipantState,
)

log = logging.getLogger(__name__)


def accept_call(
    repo: ICallingRepository,
    provider: IVideoProvider,
    *,
    call_id: UUID,
    user_id: UUID,
) -> CallDispatch:
    call = repo.get_call(call_id)
    if call is None:
        raise CallNotFoundError("Call not found.")

    me = call.participant(user_id)
    if me is None:
        raise NotParticipantError("You are not a participant in this call.")

    # The initiator is a participant, so the membership check above lets them
    # through. Accepting your own call forces it ACTIVE without anybody
    # answering: billing starts, the ring timeout no longer applies, and the
    # callee can no longer reject it ("Call is no longer ringing").
    if user_id == call.initiator_id:
        raise NotParticipantError("You cannot accept a call you started.")

    if call.status not in (CallStatus.RINGING.value, CallStatus.ACTIVE.value):
        raise CallNotRingingError("Call is no longer ringing.")

    # Re-check the block at accept — it may have been set after the call started
    # ringing. For 1:1 the counterparty is unambiguous; for a group the relevant
    # pair is accepter/initiator, which is exactly the pair _prepare_group used
    # to decide who to ring in the first place.
    if call.call_type == CallType.DM.value:
        other = next((p for p in call.participants if p.user_id != user_id), None)
        if other and repo.either_blocked(user_id, other.user_id):
            raise CallBlockedError("You cannot join this call.")
    elif user_id != call.initiator_id and repo.either_blocked(user_id, call.initiator_id):
        raise CallBlockedError("You cannot join this call.")

    if repo.active_participant_count(call_id) >= MAX_CALL_PARTICIPANTS:
        raise CallFullError("Call is full.")

    if not provider.is_configured:
        raise VideoProviderError("Calling is temporarily unavailable.")

    now = datetime.now(timezone.utc)
    try:
        repo.mark_participant_joined(call_id, user_id, now)
        started_at = repo.activate_call(call_id, now)
        repo.commit()
    except Exception:
        repo.rollback()
        raise

    try:
        creds = provider.issue_token(user_id, call.stream_call_type, call.stream_call_id)
    except Exception as exc:
        log.error("Stream token minting failed on accept for call %s: %s", call_id, exc)
        raise VideoProviderError("Calling is temporarily unavailable.") from exc

    fresh = repo.get_call(call_id)
    payload = {
        "call_id": str(call_id),
        "accepted_by": str(user_id),
        "started_at": started_at.isoformat() if started_at else None,
    }

    events: list[SocketEvent] = [
        SocketEvent(event="call_accepted", payload=payload, user_id=call.initiator_id),
        # Every device the accepter owns is ringing. Tell the rest to stop —
        # this reaches all their sockets, including the one that answered, which
        # can ignore an event naming itself.
        SocketEvent(event="call_answered_elsewhere", payload=payload, user_id=user_id),
    ]
    if call.call_type == CallType.GROUP.value:
        joined = fresh.participant(user_id) if fresh else None
        events.append(SocketEvent(
            event="call_participant_joined",
            payload={
                "call_id": str(call_id),
                "participant": {
                    "user_id": str(user_id),
                    "profile_id": joined.profile_id if joined else 0,
                    "name": joined.name if joined else "",
                    "avatar_url": joined.avatar_url if joined else None,
                    "role": joined.role if joined else "callee",
                    "state": ParticipantState.JOINED.value,
                },
            },
            group_id=call.context_id,
        ))

    return CallDispatch(
        result=to_call_out(fresh or call, creds=creds),
        socket_events=events,
        # Push as well: the accepter's other devices may be backgrounded, and a
        # phone left ringing for a call already answered on a tablet is the most
        # visible way multi-device gets this wrong.
        pushes=[PushMessage(
            user_ids=[user_id],
            data={
                "type": "call_answered_elsewhere",
                "call_id": str(call_id),
                "answered_by": str(user_id),
            },
        )],
    )


def reject_call(
    repo: ICallingRepository,
    *,
    call_id: UUID,
    user_id: UUID,
    provider: IVideoProvider | None = None,
) -> CallDispatch:
    call = repo.get_call(call_id)
    if call is None:
        raise CallNotFoundError("Call not found.")

    me = call.participant(user_id)
    if me is None:
        raise NotParticipantError("You are not a participant in this call.")

    # Same trap as accept_call: the initiator is a participant. Letting them
    # reject records their own cancellation as end_reason "rejected", which is
    # the wrong story in call history and in the chat card. Hanging up before
    # an answer is POST /end, which records it as cancelled.
    if user_id == call.initiator_id:
        raise NotParticipantError("You cannot reject a call you started.")

    if call.status != CallStatus.RINGING.value:
        raise CallNotRingingError("Call is no longer ringing.")

    now = datetime.now(timezone.utc)
    try:
        repo.mark_participant_rejected(call_id, user_id, now)

        events: list[SocketEvent] = []
        pushes: list[PushMessage] = []

        if call.call_type == CallType.DM.value:
            # 1:1 — one refusal ends it. Terminate on Stream too: nobody should
            # be billing yet, but a client that raced into the session before
            # the reject landed must be kicked out of it.
            if provider is not None:
                provider.end_call_remote(call.stream_call_type, call.stream_call_id)
            repo.end_call(call_id, CallStatus.REJECTED.value, EndReason.REJECTED.value, now)
            events.append(SocketEvent(
                event="call_rejected",
                payload={"call_id": str(call_id), "rejected_by": str(user_id)},
                user_id=call.initiator_id,
            ))
            pushes.append(PushMessage(
                user_ids=[call.initiator_id],
                data={"type": "call_ended", "call_id": str(call_id), "end_reason": EndReason.REJECTED.value},
            ))
        else:
            # Group — you drop out, the call survives.
            events.append(SocketEvent(
                event="call_participant_left",
                payload={"call_id": str(call_id), "user_id": str(user_id)},
                group_id=call.context_id,
            ))

        repo.commit()
    except Exception:
        repo.rollback()
        raise

    fresh = repo.get_call(call_id)
    return CallDispatch(
        result=CallRejectedOut(
            call_id=call_id,
            status=fresh.status if fresh else CallStatus.REJECTED.value,
        ),
        socket_events=events,
        pushes=pushes,
    )
