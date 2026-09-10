"""
Domain entities for the onboarding module.

Pure Python — no SQLAlchemy, FastAPI, Pydantic, or Redis imports.
These are plain data-holding classes that represent the business model.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class UserSession:
    """
    Represents an authenticated session for a user.

    The ``id`` doubles as the JWT ``jti`` claim, enabling per-session
    revocation without touching the access-token secret.
    The refresh token is never stored in plain text; only its SHA-256
    hash is persisted (``refresh_token_hash``).
    """

    id: uuid.UUID
    user_id: uuid.UUID
    # SHA-256 hex digest of the opaque refresh token string
    refresh_token_hash: str
    # Timestamp after which the refresh token (and session) is considered expired
    expires_at: datetime
    is_active: bool = True
    device_info: Optional[str] = None
    ip_address: Optional[str] = None
    created_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None


@dataclass
class User:
    """
    Core authentication identity.  Holds only the minimal data needed
    to identify and contact the user; richer profile data lives in the
    Profile entity (profile module).
    """

    id: uuid.UUID
    country_code: str          # e.g. "+91"
    phone_number: str          # digits only, without country code
    is_active: bool = True
    fcm_token: Optional[str] = None     # Firebase Cloud Messaging push token
    access_token: Optional[str] = None  # last-issued access token (informational)
    created_at: Optional[datetime] = None
    # Lazily populated — may be absent when the user has not yet finished onboarding
    sessions: List[UserSession] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Repository read-models — the minimal shapes the use cases actually need.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UserRef:
    """A user looked up by phone, plus whether onboarding produced a profile."""
    user_id: uuid.UUID
    profile_id: Optional[int]   # None -> user exists but never finished onboarding


@dataclass(frozen=True)
class SessionRef:
    session_id: uuid.UUID
    user_id: uuid.UUID
    expires_at: datetime


@dataclass(frozen=True)
class DevProfileRef:
    """Only used by the DEBUG-gated /auth/dev-token endpoint."""
    profile_id: int
    user_id: uuid.UUID
    name: str
