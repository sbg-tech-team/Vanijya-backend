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
    def all_followed_user_ids(self, viewer_users_id) -> set:
        """Every user this viewer follows. following_user_ids() narrows to a
        candidate list; the feed needs the whole set to mark is_following."""
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
    def record_first_view(self, post_id: int, profile_id: int) -> bool:
        """Log this profile's first view of the post and bump view_count.

        Returns False (rolling back) when the unique constraint says they have
        seen it before, so the caller can record a revisit instead. Commits.
        """
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
    def get_category_taste_weights(self, profile_id: int, role_id: int | None) -> dict[str, float]:
        """Decayed, confidence-blended category taste for this profile.

        Reads user_post_taste — the one authoritative taste store. Falls back to
        the role defaults on cold start, so the result is always usable.
        """
        ...

    @abstractmethod
    def upsert_post_embedding(
        self,
        post_id: int,
        vector: list,
        category: str,
        commodity_idx: int,
        expires_at,
        now,
        partition: str = "hot",
    ) -> None:
        """Insert or refresh this post's recommendation embedding.

        `now` is written as the embedding's created_at, which is what the expiry
        job partitions on — a backfill passes the post's real creation time and
        the matching partition, not the wall clock.

        Does not commit — it rides the caller's transaction.
        """
        ...

    @abstractmethod
    def deactivate_post_embedding(self, post_id: int) -> None:
        """Drop a post out of the recommendation index. Does not commit."""
        ...

    @abstractmethod
    def ann_post_candidates(
        self, vector: str, partition: str, limit: int, exclude_ids: set
    ) -> list[dict]:
        """HNSW cosine ANN over post_embeddings within one freshness partition.

        Rows are {"post_id", "category", "vector"}. `vector` is a pgvector
        literal. Hand-written SQL: the <=> operator has no ORM expression and
        the index is only used when ORDER BY is written this way.
        """
        ...

    @abstractmethod
    def fresh_post_candidates(
        self, cutoff, limit: int, commodity_idxs: set, exclude_ids: set
    ) -> list[dict]:
        """Recently published posts, so a new post enters the pool even when the
        ANN search ranks it below the cutoff.

        Rows are {"post_id", "category", "vector", "target_roles"}.
        """
        ...

    @abstractmethod
    def popular_post_candidates(
        self, commodity_idxs: set, exclude_ids: set, limit: int
    ) -> list:
        """Top `limit` rows from popular_posts for these commodities, by velocity."""
        ...

    @abstractmethod
    def record_seen_posts(self, profile_id: int, post_ids: list[int]) -> None:
        """Mark posts as seen by this profile. Commits."""
        ...

    @abstractmethod
    def seen_post_ids_since(self, profile_id: int, cutoff) -> set:
        """Post ids this profile has seen since `cutoff`."""
        ...

    @abstractmethod
    def user_post_feed_vector(self, users_id):
        """The stored post-feed embedding for a user, or None."""
        ...

    @abstractmethod
    def seen_post_ids(self, profile_id: int) -> set:
        ...
