"""Pure data shapes for the safety module. No SQLAlchemy, no FastAPI, no Pydantic."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class BlockedUser:
    """A user the actor has blocked, joined with their public profile fields."""
    blocked_id: UUID
    blocked_at: datetime
    name: str | None
    avatar_url: str | None


@dataclass(frozen=True)
class Report:
    id: int
    target_type: str          # user | group | post
    target_id: UUID
    reason: str
    status: str               # pending | reviewed | actioned | dismissed
    created_at: datetime
