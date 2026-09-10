from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from app.modules.onboarding.domain.entities import DevProfileRef, SessionRef, UserRef


class IOnboardingRepository(ABC):
    """Every database access in the onboarding module goes through this interface."""

    # -- users ----------------------------------------------------------------

    @abstractmethod
    def find_user_by_phone(self, country_code: str, phone_number: str) -> UserRef | None: ...

    @abstractmethod
    def get_profile_id_for_user(self, user_id: UUID) -> int | None: ...

    @abstractmethod
    def find_profile_by_name(self, name: str) -> DevProfileRef | None:
        """Case-insensitive name match. DEBUG-only dev-token endpoint."""
        ...

    # -- sessions -------------------------------------------------------------

    @abstractmethod
    def add_session(
        self,
        session_id: UUID,
        user_id: UUID,
        refresh_token_hash: str,
        expires_at: datetime,
        device_info: str | None,
        ip_address: str | None,
    ) -> None: ...

    @abstractmethod
    def get_active_session_by_refresh_hash(self, token_hash: str) -> SessionRef | None: ...

    @abstractmethod
    def rotate_refresh_token(
        self, session_id: UUID, new_hash: str, last_used_at: datetime
    ) -> None: ...

    @abstractmethod
    def deactivate_session(self, session_id: UUID) -> None: ...

    @abstractmethod
    def deactivate_all_sessions(self, user_id: UUID) -> None: ...
