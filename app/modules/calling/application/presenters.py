"""Domain entity -> response schema mapping. Pure functions, no I/O.

Kept out of the use-case files because five of them build the same CallOut.
"""
from __future__ import annotations

from app.modules.calling.application.schemas import (
    CallHistoryItemOut,
    CallOut,
    GroupSnapOut,
    ParticipantOut,
    StreamCredentialsOut,
    UserSnapOut,
)
from app.modules.calling.domain.entities import (
    CallEntity,
    CallHistoryItem,
    StreamCredentials,
)


def to_call_out(
    call: CallEntity,
    creds: StreamCredentials | None = None,
    ring_timeout: int | None = None,
) -> CallOut:
    return CallOut(
        call_id=call.id,
        call_type=call.call_type,
        media=call.media,
        status=call.status,
        created_at=call.created_at,
        started_at=call.started_at,
        ring_timeout_seconds=ring_timeout,
        stream=(
            StreamCredentialsOut(
                api_key=creds.api_key,
                token=creds.token,
                user_id=creds.user_id,
                call_type=creds.call_type,
                call_id=creds.call_id,
            )
            if creds else None
        ),
        participants=[
            ParticipantOut(
                user_id=p.user_id,
                profile_id=p.profile_id,
                name=p.name,
                avatar_url=p.avatar_url,
                role=p.role,
                state=p.state,
            )
            for p in call.participants
        ],
    )


def to_history_item(item: CallHistoryItem) -> CallHistoryItemOut:
    return CallHistoryItemOut(
        call_id=item.call_id,
        call_type=item.call_type,
        media=item.media,
        status=item.status,
        direction=item.direction,
        end_reason=item.end_reason,
        created_at=item.created_at,
        started_at=item.started_at,
        ended_at=item.ended_at,
        duration_seconds=item.duration_seconds,
        counterparty=(
            UserSnapOut(
                user_id=item.counterparty.user_id,
                profile_id=item.counterparty.profile_id,
                name=item.counterparty.name,
                avatar_url=item.counterparty.avatar_url,
            )
            if item.counterparty else None
        ),
        group=(
            GroupSnapOut(
                group_id=item.group.group_id,
                name=item.group.name,
                image_url=item.group.image_url,
            )
            if item.group else None
        ),
        participant_count=item.participant_count,
    )
