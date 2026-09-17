"""Persistence contract for the post taste store.

Kept separate from IPostRepository rather than bolted onto it: this is its own
aggregate — user_post_taste plus post_interaction_events — and IPostRepository
already carries fifty-odd methods about posts themselves.

The maths (decay, confidence blending, signal weights) stays in
post/recommendation/session_taste/; only the SQL lives behind this.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ITasteRepository(ABC):
    @property
    @abstractmethod
    def session(self) -> Any:
        """Escape hatch for the shared amplify/global-taste helpers, which still
        take a Session. Remove once app/recommendation/ takes repositories."""
        ...

    # ── Taste rows ───────────────────────────────────────────────────────────

    @abstractmethod
    def upsert_taste(
        self, profile_id: int, dimension_type: str, dimension_key: str,
        positive_delta: float, negative_delta: float, event_count: int,
    ) -> None:
        """Add deltas to one taste row, inserting it if absent. Does not commit."""
        ...

    @abstractmethod
    def taste_rows(self, profile_id: int, dimension_types: tuple[str, ...]) -> list:
        """Raw UserPostTaste rows for these dimensions, in one query."""
        ...

    @abstractmethod
    def seed_taste_rows(self, profile_id: int, category_scores: dict[str, float]) -> None:
        """Create initial category rows from role defaults. Never overwrites
        learned data. Commits."""
        ...

    # ── Interaction events ───────────────────────────────────────────────────

    @abstractmethod
    def add_interaction_events(self, events: list) -> None:
        """Queue interaction event rows. Does not commit."""
        ...

    @abstractmethod
    def unprocessed_events(self, event_types: tuple[str, ...], limit: int) -> list:
        """Oldest unprocessed events of these types."""
        ...

    @abstractmethod
    def mark_events_processed(self, event_ids: list[int], now) -> None:
        """Stamp processed_at so a batch is never counted twice. Does not commit."""
        ...

    @abstractmethod
    def repeated_ignore_pairs(self, threshold: int, limit: int) -> list:
        """(profile_id, post_id) pairs impressed `threshold` times with no
        engagement and at least one impression still unprocessed."""
        ...

    @abstractmethod
    def mark_impressions_processed(self, pairs: list, now) -> None:
        """Stamp the impressions behind those pairs. Does not commit."""
        ...

    # ── Post metadata the taste path needs ───────────────────────────────────

    @abstractmethod
    def post_taste_meta(self, post_ids: list[int]) -> dict:
        """{post_id: (category_id, commodity_id, city, state)} for these posts."""
        ...

    @abstractmethod
    def post_author_meta(self, post_ids: list[int]) -> dict:
        """{post_id: (category_id, commodity_id, author_profile_id)}."""
        ...

    @abstractmethod
    def bulk_add_events(self, rows: list) -> None:
        """Bulk-insert interaction event rows. Does not commit."""
        ...

    @abstractmethod
    def mark_posts_seen(self, profile_id: int, post_ids: list[int], now) -> None:
        """Insert seen_posts rows, ignoring ones already there. Does not commit."""
        ...

    @abstractmethod
    def get_post_for_taste(self, post_id: int):
        """The post row the revisit path needs, or None."""
        ...

    @abstractmethod
    def rollback(self) -> None:
        ...

    @abstractmethod
    def profile_exists(self, profile_id: int) -> bool:
        ...

    @abstractmethod
    def commit(self) -> None:
        ...
