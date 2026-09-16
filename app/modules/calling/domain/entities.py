"""Calling domain entities — plain dataclasses the repository returns.

The application layer works with these, never with SQLAlchemy models, so use
cases stay free of ORM/session concerns.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass
class UserSnap:
    """Denormalised identity for a call participant. Avatar may be None —
    clients fall back to initials from `name`."""
    user_id: UUID
    profile_id: int
    name: str
    avatar_url: str | None = None


@dataclass
class GroupSnap:
    group_id: UUID
    name: str
    image_url: str | None = None


@dataclass
class ParticipantEntity:
    user_id: UUID
    profile_id: int
    name: str
    avatar_url: str | None
    role: str            # ParticipantRole
    state: str           # ParticipantState
    joined_at: datetime | None = None
    left_at: datetime | None = None


@dataclass
class CallEntity:
    id: UUID
    stream_call_type: str
    stream_call_id: str
    call_type: str       # CallType
    media: str           # CallMedia
    status: str          # CallStatus
    context_id: UUID     # conversation_id for dm, group_id for group
    initiator_id: UUID
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_seconds: int = 0
    end_reason: str | None = None
    participants: list[ParticipantEntity] = field(default_factory=list)

    def is_terminal(self) -> bool:
        from app.modules.calling.domain.value_objects import TERMINAL_STATUSES
        return self.status in TERMINAL_STATUSES

    def participant(self, user_id: UUID) -> ParticipantEntity | None:
        return next((p for p in self.participants if p.user_id == user_id), None)


@dataclass
class CallHistoryItem:
    """One row of GET /calls. `counterparty` is set for dm, `group` for group."""
    call_id: UUID
    call_type: str
    media: str
    status: str
    direction: str            # "outgoing" | "incoming"
    end_reason: str | None
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    duration_seconds: int
    counterparty: UserSnap | None = None
    group: GroupSnap | None = None
    participant_count: int = 0


@dataclass
class StreamCredentials:
    """Short-lived join credentials handed to the client. Never persisted."""
    api_key: str
    token: str
    user_id: UUID
    call_type: str
    call_id: str
    expires_at: datetime


@dataclass
class PushTarget:
    """One device to ring. `fcm_token` may be None — such users are skipped."""
    user_id: UUID
    fcm_token: str | None
