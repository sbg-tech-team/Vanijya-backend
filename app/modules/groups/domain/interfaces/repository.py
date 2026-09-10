from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional
from uuid import UUID


class IGroupsRepository(ABC):
    """Every database access in the groups module goes through this interface."""

    @property
    @abstractmethod
    def session(self) -> Any:
        """Escape hatch for cross-module helpers that still take a Session."""
        ...

    @abstractmethod
    def add(self, obj) -> None:
        ...

    @abstractmethod
    def delete(self, obj) -> None:
        ...

    @abstractmethod
    def flush(self) -> None:
        ...

    @abstractmethod
    def commit(self) -> None:
        ...

    @abstractmethod
    def rollback(self) -> None:
        ...

    @abstractmethod
    def refresh(self, obj) -> None:
        ...

    @abstractmethod
    def get_profile_by_user(self, user_id: UUID) -> Optional[Profile]:
        ...

    @abstractmethod
    def get_profile_by_id(self, profile_id: int) -> Optional[Profile]:
        ...

    @abstractmethod
    def get_profiles_with_role(self, user_ids: list[UUID]) -> dict:
        ...

    @abstractmethod
    def get_group(self, group_id: UUID) -> Optional[Group]:
        ...

    @abstractmethod
    def get_group_by_invite_token(self, token: str) -> Optional[Group]:
        ...

    @abstractmethod
    def get_groups_by_ids(self, group_ids: list[UUID]) -> dict:
        ...

    @abstractmethod
    def search_groups(self, *, commodity: str | None, accessibility: str | None, name_q: str | None, region_market: str | None, target_role: str | None, page: int, per_page: int) -> tuple[list[Group], int]:
        ...

    @abstractmethod
    def get_membership(self, group_id: UUID, user_id: UUID) -> Optional[GroupMember]:
        ...

    @abstractmethod
    def get_other_admin(self, group_id: UUID, user_id: UUID) -> Optional[GroupMember]:
        ...

    @abstractmethod
    def count_members(self, group_id: UUID) -> int:
        ...

    @abstractmethod
    def list_members(self, group_id: UUID, page: int, limit: int) -> list[GroupMember]:
        ...

    @abstractmethod
    def admin_group_ids(self, user_id: UUID) -> set:
        ...

    @abstractmethod
    def member_group_ids(self, user_id: UUID) -> set:
        ...

    @abstractmethod
    def get_pending_join_request(self, group_id: UUID, user_id: UUID) -> Optional[GroupJoinRequest]:
        ...

    @abstractmethod
    def get_join_request(self, group_id: UUID, request_id: int) -> Optional[GroupJoinRequest]:
        ...

    @abstractmethod
    def list_join_requests(self, group_id: UUID, status: str | None, page: int, limit: int) -> tuple[list[GroupJoinRequest], int]:
        ...

    @abstractmethod
    def list_join_requests_for_groups(self, group_ids: list, status: str | None = 'pending') -> list[GroupJoinRequest]:
        ...

    @abstractmethod
    def list_my_join_requests(self, user_id: UUID) -> list[GroupJoinRequest]:
        ...

    @abstractmethod
    def count_media(self, group_id: UUID) -> int:
        ...

    @abstractmethod
    def list_media(self, group_id: UUID, page: int, limit: int) -> list[GroupMedia]:
        ...

    @abstractmethod
    def get_media(self, group_id: UUID, media_id) -> Optional[GroupMedia]:
        ...

    @abstractmethod
    def count_deals(self, group_id: UUID) -> int:
        ...

    @abstractmethod
    def list_deals(self, group_id: UUID, page: int, limit: int) -> list[GroupDeal]:
        ...

    @abstractmethod
    def get_deal(self, group_id: UUID, deal_id: UUID) -> Optional[GroupDeal]:
        ...

    @abstractmethod
    def upsert_embedding(self, group_id: UUID, vec) -> None:
        ...

    @abstractmethod
    def get_activity_cache(self, group_ids: list[UUID]) -> dict:
        ...

    @abstractmethod
    def list_admin_pending_requests(self, admin_group_ids: list, page: int, limit: int) -> tuple[list, int]:
        """(GroupJoinRequest, Group.name) rows for every group the user admins."""
        ...

    @abstractmethod
    def raw_sql(self, sql: str, params: dict) -> list[dict]:
        """Rows as dicts. Used by the hand-written pgvector ANN query."""
        ...
