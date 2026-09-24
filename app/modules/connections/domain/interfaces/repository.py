from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional
from uuid import UUID


class IConnectionsRepository(ABC):
    """Every database access in the connections module goes through this interface.

Methods return SQLAlchemy model instances rather than domain dataclasses: the
response formatter reads Profile.role / .business / .commodities relationships
directly, exactly as app_old did, and re-wrapping them would change the
eager-loading behaviour."""

    @abstractmethod
    def load_profile(self, user_id: UUID):
        ...

    @abstractmethod
    def load_profiles_bulk(self, user_ids: list[UUID]) -> dict:
        """{users_id: Profile}, one query, role/business/commodities eager-loaded."""
        ...

    @abstractmethod
    def bulk_statuses(self, me: UUID, target_ids: list[UUID]) -> dict:
        """{uid: {"msg_req_status": str|None, "follow_status": bool}} in two queries."""
        ...

    @abstractmethod
    def get_follow(self, follower_id: UUID, following_id: UUID):
        ...

    @abstractmethod
    def add_follow(self, follower_id: UUID, following_id: UUID) -> None:
        """Insert the edge and bump both counters, in one transaction."""
        ...

    @abstractmethod
    def remove_follow(self, follower_id: UUID, following_id: UUID) -> bool:
        """Delete the edge, decrement counters (floored at 0) and drop the"""
        ...

    @abstractmethod
    def list_followers(self, user_id: UUID) -> list:
        ...

    @abstractmethod
    def reconcile_follow_counts(self) -> int:
        """Recompute followers_count/following_count from user_connections and
        correct any profile whose stored value disagrees. Only writes rows
        that are actually wrong. Returns the number of profiles corrected."""
        ...

    @abstractmethod
    def list_following(self, user_id: UUID) -> list:
        ...

    @abstractmethod
    def get_message_request(self, sender_id: UUID, receiver_id: UUID):
        ...

    @abstractmethod
    def get_message_request_by_id(self, request_id: int):
        ...

    @abstractmethod
    def get_pending_request_for_receiver(self, request_id: int, me: UUID):
        ...

    @abstractmethod
    def add_message_request(self, sender_id: UUID, receiver_id: UUID, message: str | None):
        ...

    @abstractmethod
    def delete_withdrawable_request(self, sender_id: UUID, receiver_id: UUID) -> bool:
        """Withdraw only a pending/declined request, as app_old did."""
        ...

    @abstractmethod
    def set_message_request_status(self, request, status: str) -> None:
        ...

    @abstractmethod
    def revive_declined_request(self, request, message: str | None):
        """A declined request can be re-sent: back to pending, acted_at cleared."""
        ...

    @abstractmethod
    def list_received_requests(self, me: UUID) -> list:
        ...

    @abstractmethod
    def list_sent_requests(self, me: UUID) -> list:
        ...

    @abstractmethod
    def commit(self) -> None:
        ...

    @abstractmethod
    def find_role_by_name(self, name: str):
        ...

    @abstractmethod
    def search_profiles(self, me: UUID, *, role: str | None, commodity: str | None, city: str | None, q: str | None, user_verified_only: bool, business_verified_only: bool, page: int, limit: int) -> tuple[list, int]:
        """One page of matching profiles plus the unpaginated total."""
        ...

    @abstractmethod
    def suggest_profiles(self, q: str, limit: int) -> list:
        ...

    @abstractmethod
    def find_dm_between(self, a: UUID, b: UUID):
        ...

    @abstractmethod
    def create_dm(self, initiator_id: UUID, other_id: UUID, now: datetime) -> UUID:
        ...

    @abstractmethod
    def activate_dm(self, conv) -> None:
        ...

    @abstractmethod
    def seed_first_message(self, conv_id: UUID, sender_id: UUID, body: str) -> None:
        ...

    @abstractmethod
    def count_recommendable_users(self, user_id: UUID, seen_ids: list[str]) -> int:
        """How many candidates the ANN search could return for this user.

        Excludes the user, anyone they already follow, anyone they have a
        pending message request with, and `seen_ids`.
        """
        ...

    @abstractmethod
    def ann_user_candidates(
        self, vector: str, user_id: UUID, seen_ids: list[str], limit: int, offset: int
    ) -> list[dict]:
        """One page of cosine-ANN matches under the same exclusions.

        Rows are {"user_id", "similarity"}. `vector` is a pgvector literal.
        """
        ...

    @abstractmethod
    def ann_user_candidates_unfiltered(self, vector: str, limit: int) -> list[dict]:
        """Cosine-ANN matches with no exclusions — the signed-out preview search."""
        ...

