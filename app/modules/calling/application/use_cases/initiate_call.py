"""Start a call — POST /calls.

Permission model (as specced): any user may call any other user. There is NO
relationship requirement. The only gates are:
  * not yourself
  * neither party has blocked the other
  * group calls require membership
  * neither party is already on a call (1:1); caller only (group)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

import redis as redis_lib

from app.modules.calling.application.budget import check_budget
from app.modules.calling.application.dispatch import CallDispatch, PushMessage, SocketEvent
from app.modules.calling.application.presenters import to_call_out
from app.modules.calling.domain.exceptions import (
    CallBlockedError,
    CallBudgetExceededError,
    CalleeBusyError,
    CallerBusyError,
    CallFullError,
    CallTargetNotFoundError,
    NotGroupMemberError,
    SelfCallError,
    VideoNotAvailableError,
    VideoProviderError,
)
from app.modules.calling.domain.interfaces.repository import ICallingRepository
from app.modules.calling.domain.interfaces.video_provider import IVideoProvider
from app.modules.calling.domain.value_objects import (
    MAX_CALL_DURATION_SECONDS,
    MAX_CALL_PARTICIPANTS,
    RING_TIMEOUT_SECONDS,
    CallMedia,
    CallType,
)

log = logging.getLogger(__name__)


def initiate_call(
    repo: ICallingRepository,
    provider: IVideoProvider,
    *,
    caller_id: UUID,
    call_type: str,
    target_user_id: UUID | None,
    group_id: UUID | None,
    media: str,
    rc: "redis_lib.Redis | None" = None,
) -> CallDispatch:
    if media == CallMedia.VIDEO.value:
        raise VideoNotAvailableError("Video calling is not yet available.")
    if not provider.is_configured:
        raise VideoProviderError("Calling is temporarily unavailable.")

    caller = repo.get_user_snap(caller_id)
    if caller is None:
        raise CallTargetNotFoundError("Your profile was not found.")

    # Serialise everyone this call touches BEFORE the busy check. The check and
    # the insert are otherwise check-then-act: two taps in the same instant both
    # see the user free and both create a call, billing in parallel.
    lock_ids = [caller_id] + ([target_user_id] if target_user_id else [])
    repo.lock_users_for_call(lock_ids)

    if repo.busy_call_id(caller_id) is not None:
        raise CallerBusyError("You are already in a call.")

    # Spend guardrail: refuse the call if this user or the platform as a whole
    # has burned through its participant-minute budget. Fails OPEN on a Redis
    # outage — the duration caps still bound the damage.
    budget_block = check_budget(rc, caller_id)
    if budget_block:
        raise CallBudgetExceededError(budget_block)

    if call_type == CallType.DM.value:
        context_id, participant_ids, group = _prepare_dm(repo, caller_id, target_user_id)
    else:
        context_id, participant_ids, group = _prepare_group(repo, caller_id, group_id)
        # Members become participants, so they need the same serialisation the
        # 1:1 path gives the callee.
        repo.lock_users_for_call(participant_ids)

    now = datetime.now(timezone.utc)
    call_id = uuid4()
    stream_call_type, stream_call_id = provider.new_call_id(call_id)

    try:
        call = repo.create_call(
            call_id=call_id,
            stream_call_type=stream_call_type,
            stream_call_id=stream_call_id,
            call_type=call_type,
            media=media,
            context_id=context_id,
            initiator_id=caller_id,
            participant_ids=participant_ids,
            now=now,
        )
        repo.commit()   # releases the advisory locks
    except Exception:
        repo.rollback()
        raise

    # Provision AFTER the row exists, so a failed DB write cannot leave an
    # orphaned session on the provider. Carries the hard duration cap — the only
    # guardrail that still works if our backend dies mid-call, since the provider
    # ends the session itself once the limit is hit. Best-effort: a provider blip
    # must not stop people calling, it only means our own sweeps become the outer
    # bound instead.
    provider.provision_call(
        stream_call_type=stream_call_type,
        stream_call_id=stream_call_id,
        created_by_id=caller_id,
        max_duration_seconds=MAX_CALL_DURATION_SECONDS,
    )

    try:
        creds = provider.issue_token(caller_id, stream_call_type, stream_call_id)
    except Exception as exc:
        # The call row exists but is unjoinable — terminalise it so the caller
        # is not left "busy" and blocked from retrying.
        repo.end_call(call_id, "failed", "failed", now)
        repo.commit()
        log.error("Stream token minting failed for call %s: %s", call_id, exc)
        raise VideoProviderError("Calling is temporarily unavailable.") from exc

    callee_ids = [uid for uid in participant_ids if uid != caller_id]
    ring_payload = to_call_out(call, ring_timeout=RING_TIMEOUT_SECONDS).model_dump(mode="json")

    return CallDispatch(
        result=to_call_out(call, creds=creds, ring_timeout=RING_TIMEOUT_SECONDS),
        socket_events=[
            SocketEvent(event="incoming_call", payload=ring_payload, user_id=uid)
            for uid in callee_ids
        ],
        pushes=[PushMessage(
            user_ids=callee_ids,
            data={
                "type": "incoming_call",
                "call_id": str(call.id),
                "call_type": call.call_type,
                "media": call.media,
                "caller_user_id": str(caller.user_id),
                "caller_name": caller.name,
                "caller_avatar_url": caller.avatar_url or "",
                "group_id": str(group.group_id) if group else "",
                "group_name": group.name if group else "",
                "created_at": call.created_at.isoformat(),
                "ring_timeout_seconds": str(RING_TIMEOUT_SECONDS),
            },
        )],
    )


# ── Target preparation ────────────────────────────────────────────────────────

def _prepare_dm(
    repo: ICallingRepository, caller_id: UUID, target_user_id: UUID | None
):
    if target_user_id == caller_id:
        raise SelfCallError("You cannot call yourself.")

    target = repo.get_user_snap(target_user_id) if target_user_id else None
    if target is None:
        raise CallTargetNotFoundError("User not found.")

    if repo.either_blocked(caller_id, target_user_id):
        raise CallBlockedError("You cannot call this user.")

    if repo.busy_call_id(target_user_id) is not None:
        raise CalleeBusyError("User is already in a call.")

    # A call is itself consent to converse, so the DM is created if absent —
    # the same rule message-request accept applies.
    context_id = repo.get_or_create_dm_id(caller_id, target_user_id)
    return context_id, [caller_id, target_user_id], None


def _prepare_group(repo: ICallingRepository, caller_id: UUID, group_id: UUID | None):
    group = repo.get_group_snap(group_id) if group_id else None
    if group is None:
        raise CallTargetNotFoundError("Group not found.")

    if not repo.is_group_member(group_id, caller_id):
        raise NotGroupMemberError("You are not a member of this group.")

    member_ids = repo.group_member_ids(group_id)

    # Members who have blocked the caller (or are blocked by them) are simply
    # not rung. The call still happens for everyone else.
    ringable = [
        uid for uid in member_ids
        if uid == caller_id or not repo.either_blocked(caller_id, uid)
    ]
    if caller_id not in ringable:
        ringable.insert(0, caller_id)

    if len(ringable) > MAX_CALL_PARTICIPANTS:
        raise CallFullError(
            f"Group calls are limited to {MAX_CALL_PARTICIPANTS} participants."
        )

    return group_id, ringable, group
