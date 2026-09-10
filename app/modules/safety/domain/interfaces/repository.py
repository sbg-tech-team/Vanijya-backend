from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from app.modules.safety.domain.entities import BlockedUser, Report


class ISafetyRepository(ABC):
    """Every database access in the safety module goes through this interface."""

    # -- blocks ---------------------------------------------------------------

    @abstractmethod
    def block_exists(self, blocker_id: UUID, blocked_id: UUID) -> bool: ...

    @abstractmethod
    def add_block(self, blocker_id: UUID, blocked_id: UUID) -> None: ...

    @abstractmethod
    def remove_block(self, blocker_id: UUID, blocked_id: UUID) -> bool:
        """True if a row was deleted, False if there was nothing to delete."""
        ...

    @abstractmethod
    def list_blocked(
        self, blocker_id: UUID, page: int, limit: int
    ) -> tuple[list[BlockedUser], int]:
        """One page of blocked users (newest first) plus the unpaginated total."""
        ...

    @abstractmethod
    def either_blocked(self, user_a: UUID, user_b: UUID) -> bool: ...

    # -- reports --------------------------------------------------------------

    @abstractmethod
    def report_exists(self, reporter_id: UUID, target_type: str, target_id: UUID) -> bool: ...

    @abstractmethod
    def add_report(
        self,
        reporter_id: UUID,
        target_type: str,
        target_id: UUID,
        reason: str,
        description: str | None,
    ) -> Report: ...

    @abstractmethod
    def list_reports(
        self, reporter_id: UUID, page: int, limit: int
    ) -> tuple[list[Report], int]: ...
