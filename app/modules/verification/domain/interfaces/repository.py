from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from app.modules.verification.domain.entities import DocRecord, ProfileRef, VerificationOutcome


class IVerificationRepository(ABC):
    """Every database access in the verification module goes through this interface."""

    @abstractmethod
    def get_profile_by_user(self, user_id: UUID) -> ProfileRef | None: ...

    @abstractmethod
    def save_verification(
        self,
        profile_id: int,
        document_type: str,
        category: str,
        document_number: str,
        status: str,
        api_provider: str,
        api_response: dict | None,
        error_message: str | None,
        verified_at: datetime | None,
        now: datetime,
        mark_profile_verified: bool,
    ) -> VerificationOutcome:
        """Upsert the record and, when verified, flip the profile flag — one transaction."""
        ...

    @abstractmethod
    def list_records(self, profile_id: int) -> list[DocRecord]: ...
