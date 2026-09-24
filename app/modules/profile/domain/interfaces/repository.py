from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from uuid import UUID

from app.modules.profile.domain.entities import NotificationPrefs, ProfileEntity, UserEntity


class IProfileRepository(ABC):

    # -------------------------------------------------------------------------
    # User
    # -------------------------------------------------------------------------

    @abstractmethod
    def get_user(self, user_id: UUID) -> UserEntity | None: ...

    @abstractmethod
    def phone_number_exists(self, country_code: str, phone_number: str) -> bool: ...

    @abstractmethod
    def create_user(self, user_id: UUID, phone_number: str, country_code: str) -> UserEntity: ...

    @abstractmethod
    def delete_user(self, user_id: UUID) -> None: ...

    @abstractmethod
    def get_access_token(self, user_id: UUID) -> str | None: ...

    @abstractmethod
    def store_access_token(self, user_id: UUID, token: str) -> None: ...

    @abstractmethod
    def update_fcm_token(self, user_id: UUID, fcm_token: str) -> None: ...

    # -------------------------------------------------------------------------
    # Profile — lookups
    # -------------------------------------------------------------------------

    @abstractmethod
    def get_profile_for_user(
        self, user_id: UUID, with_follow_counts: bool = False
    ) -> ProfileEntity | None:
        """Full load: user + business + commodities (with names) + interests (with names)."""
        ...

    @abstractmethod
    def get_profile_by_id(
        self, profile_id: int, with_follow_counts: bool = False
    ) -> ProfileEntity | None:
        """Public load: business + commodities (with names). No user row."""
        ...

    @abstractmethod
    def get_profile_by_user_id(
        self, user_id: UUID, with_follow_counts: bool = False
    ) -> ProfileEntity | None:
        """Public load: business + commodities (with names). No user row."""
        ...

    @abstractmethod
    def get_profile_id_for_user(self, user_id: UUID) -> int | None: ...

    @abstractmethod
    def user_has_profile(self, user_id: UUID) -> bool: ...

    # -------------------------------------------------------------------------
    # Profile — mutations
    # -------------------------------------------------------------------------

    @abstractmethod
    def create_profile(
        self,
        user_id: UUID,
        role_id: int,
        name: str,
        qty_min: Decimal,
        qty_max: Decimal,
        business_name: str | None,
        city: str | None,
        state: str | None,
        latitude: float,
        longitude: float,
        commodity_ids: list[int],
        interest_ids: list[int],
    ) -> None:
        """Creates Profile + Business + commodity/interest junctions atomically."""
        ...

    @abstractmethod
    def update_profile(
        self,
        user_id: UUID,
        scalar_fields: dict,
        business_fields: dict,
        commodity_to_add: set[int],
        commodity_to_remove: set[int],
        interest_to_add: set[int],
        interest_to_remove: set[int],
    ) -> None:
        """Applies all field, business, commodity, and interest changes in one transaction."""
        ...

    @abstractmethod
    def delete_profile(self, user_id: UUID) -> None: ...

    @abstractmethod
    def update_avatar_url(self, profile_id: int, avatar_url: str) -> None: ...

    # -------------------------------------------------------------------------
    # Lookup-table validation
    # -------------------------------------------------------------------------

    @abstractmethod
    def role_exists(self, role_id: int) -> bool: ...

    @abstractmethod
    def find_missing_commodity_ids(self, ids: list[int]) -> list[int]: ...

    @abstractmethod
    def find_missing_interest_ids(self, ids: list[int]) -> list[int]: ...

    # -------------------------------------------------------------------------
    # Embeddings
    # -------------------------------------------------------------------------

    @abstractmethod
    def upsert_embedding(
        self,
        user_id: UUID,
        is_vector: list[float],
        post_feed_vector: list[float],
    ) -> None: ...

    # -------------------------------------------------------------------------
    # Cross-module data (post counts, follow graph, message requests)
    # -------------------------------------------------------------------------

    @abstractmethod
    def count_posts_for_profile(self, profile_id: int) -> int: ...

    @abstractmethod
    def get_follow_status(self, follower_user_id: UUID, following_user_id: UUID) -> bool: ...

    @abstractmethod
    def get_message_request_status(self, user_a_id: UUID, user_b_id: UUID) -> str | None: ...

    @abstractmethod
    def get_profile_posts_feed(
        self,
        profile_id: int,
        cursor: int | None,
        limit: int,
    ) -> tuple[list, int | None, int]:
        """Returns (posts, next_cursor, page_count). page_count is the number of
        posts in this page, not the user's total. Rendering them as feed cards
        is the use case's job — see get_profile."""
        ...

    @abstractmethod
    def get_notification_prefs(self, user_id: UUID) -> "NotificationPrefs":
        """All-on for a user with no row — nobody is created one until they
        change a switch."""
        ...

    @abstractmethod
    def set_notification_prefs(
        self,
        user_id: UUID,
        push_enabled: bool | None = None,
        market_alerts_enabled: bool | None = None,
        group_enabled: bool | None = None,
    ) -> "NotificationPrefs":
        """Partial: None leaves that switch untouched."""
        ...
