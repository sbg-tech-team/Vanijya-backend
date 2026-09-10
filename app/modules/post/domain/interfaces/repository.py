from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional
from uuid import UUID


class IPostRepository(ABC):
    """Every database access in the post module goes through this interface."""

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
    def active_profile_ids(self) -> list[int]:
        ...

    @abstractmethod
    def get_profile(self, profile_id: int) -> Optional[Profile]:
        ...

    @abstractmethod
    def get_profile_by_user(self, user_id: UUID) -> Optional[Profile]:
        ...

    @abstractmethod
    def get_profile_with_business(self, profile_id: int) -> Optional[Profile]:
        ...

    @abstractmethod
    def get_profile_with_commodities(self, profile_id: int) -> Optional[Profile]:
        ...

    @abstractmethod
    def get_authors_with_business(self, profile_ids: list[int]) -> dict:
        ...

    @abstractmethod
    def get_user_id_for_profile(self, profile_id: int):
        ...

    @abstractmethod
    def following_user_ids(self, viewer_users_id, candidate_uids: list) -> set:
        ...

    @abstractmethod
    def followed_profile_ids(self, viewer_users_id) -> list[int]:
        ...

    @abstractmethod
    def get_post(self, post_id: int) -> Optional[Post]:
        ...

    @abstractmethod
    def get_active_post(self, post_id: int) -> Optional[Post]:
        ...

    @abstractmethod
    def list_active_posts(self, limit: int, offset: int) -> list[Post]:
        ...

    @abstractmethod
    def list_my_posts(self, profile_id: int, cursor_post_id: int | None, limit: int) -> list[Post]:
        ...

    @abstractmethod
    def list_following_posts(self, followed_profile_ids: list[int], cutoff: datetime, seen_ids: set) -> list[Post]:
        ...

    @abstractmethod
    def has_seen_recent_followed_post(self, followed_profile_ids: list[int], cutoff: datetime, seen_ids: set) -> bool:
        ...

    @abstractmethod
    def increment_view_count(self, post_id: int) -> bool:
        """True if the view was counted; False on a duplicate (caller logs a revisit)."""
        ...

    @abstractmethod
    def get_posts_by_ids(self, post_ids: list[int]) -> list[Post]:
        ...

    @abstractmethod
    def increment_view_count_no_commit(self, post_id: int) -> None:
        ...

    @abstractmethod
    def is_liked(self, post_id: int, profile_id: int) -> bool:
        ...

    @abstractmethod
    def is_saved(self, post_id: int, profile_id: int) -> bool:
        ...

    @abstractmethod
    def liked_post_ids(self, profile_id: int, post_ids: list[int]) -> set:
        ...

    @abstractmethod
    def saved_post_ids(self, profile_id: int, post_ids: list[int]) -> set:
        ...

    @abstractmethod
    def get_like(self, post_id: int, profile_id: int) -> Optional[PostLike]:
        ...

    @abstractmethod
    def get_save(self, post_id: int, profile_id: int) -> Optional[PostSave]:
        ...

    @abstractmethod
    def list_saves(self, profile_id: int, cursor_save_id: int | None, limit: int) -> list[PostSave]:
        ...

    @abstractmethod
    def bump_counter(self, post_id: int, column: str, delta: int) -> None:
        """Increment/decrement a denormalised counter on posts, no commit."""
        ...

    @abstractmethod
    def get_profile_with_business_by_id(self, profile_id: int):
        ...

    @abstractmethod
    def get_commenters_with_business(self, profile_ids: list[int]) -> dict:
        ...

    @abstractmethod
    def list_comments_asc(self, post_id: int, cursor_comment_id: int | None, limit: int):
        ...

    @abstractmethod
    def get_comment_on_post(self, post_id: int, comment_id: int):
        ...

    @abstractmethod
    def get_comment(self, comment_id: int) -> Optional[PostComment]:
        ...

    @abstractmethod
    def list_comments(self, post_id: int, cursor_id: int | None, limit: int) -> list[PostComment]:
        ...

    @abstractmethod
    def get_taste_profile(self, profile_id: int) -> Optional[UserTasteProfile]:
        ...

    @abstractmethod
    def seen_post_ids(self, profile_id: int) -> set:
        ...
