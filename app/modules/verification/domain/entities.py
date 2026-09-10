"""Pure verification shapes. No SQLAlchemy, no FastAPI, no Pydantic."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ProfileRef:
    """The only profile fields the verification rules need."""
    profile_id: int
    role_id: int | None
    is_user_verified: bool
    is_business_verified: bool


@dataclass(frozen=True)
class VerificationOutcome:
    """What the client is told after a verification attempt."""
    document_type: str                 # pan | aadhaar | gst | iec
    status: str                        # verified | error
    verified_at: datetime | None


@dataclass(frozen=True)
class DocRecord:
    """A stored verification_records row, as the status endpoint reads it."""
    verification_category: str         # kyc | kyb
    document_type: str
    status: str
    verified_at: datetime | None
