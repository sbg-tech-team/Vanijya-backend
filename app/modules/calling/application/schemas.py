"""Calling schemas.

Defined in the application layer so use cases can build responses without
importing from presentation/. presentation/schemas.py re-exports every name,
so router imports and the wire format are unchanged.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


# ── Requests ──────────────────────────────────────────────────────────────────

class CallCreate(BaseModel):
    call_type: Literal["dm", "group"]
    target_user_id: Optional[UUID] = None    # dm only
    group_id: Optional[UUID] = None          # group only
    media: Literal["audio", "video"] = "audio"

    @model_validator(mode="after")
    def target_matches_type(self) -> "CallCreate":
        if self.call_type == "dm":
            if self.target_user_id is None:
                raise ValueError("target_user_id is required for a dm call")
            if self.group_id is not None:
                raise ValueError("group_id must be omitted for a dm call")
        else:
            if self.group_id is None:
                raise ValueError("group_id is required for a group call")
            if self.target_user_id is not None:
                raise ValueError("target_user_id must be omitted for a group call")
        return self


# ── Response fragments ────────────────────────────────────────────────────────

class StreamCredentialsOut(BaseModel):
    api_key: str
    token: str
    user_id: UUID
    call_type: str
    call_id: str


class ParticipantOut(BaseModel):
    user_id: UUID
    profile_id: int
    name: str
    avatar_url: Optional[str] = None
    role: str
    state: str


class UserSnapOut(BaseModel):
    user_id: UUID
    profile_id: int
    name: str
    avatar_url: Optional[str] = None


class GroupSnapOut(BaseModel):
    group_id: UUID
    name: str
    image_url: Optional[str] = None


# ── Responses ─────────────────────────────────────────────────────────────────

class CallOut(BaseModel):
    """Full call object. `stream` is present only where a token is issued
    (initiate and accept) — never on reads."""
    call_id: UUID
    call_type: str
    media: str
    status: str
    created_at: datetime
    started_at: Optional[datetime] = None
    ring_timeout_seconds: Optional[int] = None
    stream: Optional[StreamCredentialsOut] = None
    participants: list[ParticipantOut] = Field(default_factory=list)


class CallRejectedOut(BaseModel):
    call_id: UUID
    status: str


class CallEndedOut(BaseModel):
    call_id: UUID
    status: str
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_seconds: int
    end_reason: Optional[str] = None


class CallHeartbeatOut(BaseModel):
    call_id: UUID
    status: str
    next_heartbeat_in_seconds: int


class CallTokenOut(BaseModel):
    token: str
    expires_at: datetime


class CallHistoryItemOut(BaseModel):
    call_id: UUID
    call_type: str
    media: str
    status: str
    direction: str
    end_reason: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_seconds: int
    counterparty: Optional[UserSnapOut] = None
    group: Optional[GroupSnapOut] = None
    participant_count: int = 0


class CallHistoryOut(BaseModel):
    calls: list[CallHistoryItemOut] = Field(default_factory=list)
    next_cursor: Optional[str] = None
