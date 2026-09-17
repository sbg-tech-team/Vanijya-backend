"""
Abstract repository contract for the news module.

NewsRepository (data/repository.py) implements this.

Scope: covers everything the application use cases need via this interface.
The recommendation layer (recommendation/engine.py, taste_service.py) accesses
data/models.py directly — it does not go through this interface.

Transaction ownership: the repository does NOT commit by default. Each method
performs its DB work (add / update / delete / flush) but leaves the commit to
the caller. The application use case calls repo.commit() once it has completed
all operations for a logical unit of work. The two exceptions are methods that
explicitly note they commit (e.g. save_raw_article for single-article upserts
in the ingestion loop where each article is its own transaction unit).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

from app.modules.news.domain.entities import (
    EnrichedArticle,
    FeedRankingCache,
    NewsArticleStats,
    NewsInteractionEvent,
    RawArticle,
)
from app.modules.news.domain.value_objects import IntelligenceStatus


class INewsRepository(ABC):

    # ── Transaction control ───────────────────────────────────────────────────


    @abstractmethod
    def commit(self) -> None:
        """Commit the current transaction."""

    @abstractmethod
    def rollback(self) -> None:
        """Roll back the current transaction."""

    # ── Ingestion ─────────────────────────────────────────────────────────────

    @abstractmethod
    def save_raw_article(self, article: RawArticle) -> RawArticle:
        """
        Upsert a raw article by external_id.
        ON CONFLICT (external_id) DO NOTHING — dedup is the caller's intent.
        Returns the entity with id populated (either new or existing).
        Commits per-article (each article is its own transaction unit in the
        ingestion loop so partial runs don't lose work on failure).
        """

    @abstractmethod
    def get_pending_raw_articles(self, limit: int) -> list[RawArticle]:
        """Return up to `limit` articles with intelligence_status = PENDING."""

    @abstractmethod
    def mark_intelligence_status(
        self,
        article_id: UUID,
        status: IntelligenceStatus,
    ) -> None:
        """Update the intelligence_status of a raw article. Does not commit."""

    @abstractmethod
    def get_ingestion_stats(self) -> dict:
        """
        Return counts of raw articles grouped by intelligence_status.
        e.g. {"pending": 12, "enriched": 340, "failed": 5, "processing": 1}
        """

    @abstractmethod
    def archive_old_raw_articles(self, days_old: int = 30) -> int:
        """
        Set is_active=False on raw articles older than `days_old` days.
        Commits. Returns the number of articles archived.
        """

    @abstractmethod
    def recalc_trending(self) -> int:
        """
        Recompute and atomically replace the whole trending snapshot.

        Velocity score = distinct profiles that interacted with an article in
        the past TRENDING_LOOKBACK_H hours (open_article, dwell, like, share),
        normalised against the busiest article. Articles below
        TRENDING_MIN_UNIQUE_USERS are dropped. Commits. Returns the snapshot
        size.
        """

    # ── Intelligence ──────────────────────────────────────────────────────────

    @abstractmethod
    def save_enriched_article(self, article: EnrichedArticle) -> None:
        """
        Insert or replace the EnrichedArticle for a given raw_article_id.
        Commits (each enrichment is its own transaction unit).
        """

    # ── Article existence / lookup ────────────────────────────────────────────

    @abstractmethod
    def article_exists(self, article_id: UUID) -> bool:
        """Return True if a RawArticle with this id exists."""

    @abstractmethod
    def filter_valid_article_ids(self, article_ids: list[UUID]) -> set[UUID]:
        """
        Given a list of article_ids (e.g. from a client event batch), return
        only those that exist in news_raw_articles. Used for stale-drop.
        """

    @abstractmethod
    def get_primary_factor_for_article(self, article_id: UUID) -> str | None:
        """
        Return the primary_factor of the EnrichedArticle linked to this
        raw article_id. Returns None if the article has not been enriched yet.
        Used by the interaction layer to update taste on like / save / revisit.
        """

    # ── Views ─────────────────────────────────────────────────────────────────

    @abstractmethod
    def upsert_view(self, profile_id: int, article_id: UUID) -> bool:
        """
        Create a NewsView row if none exists (first open), or increment
        view_count and update last_viewed_at if one already exists (revisit).
        Does not commit.
        Returns True if this was a revisit (row already existed), False if new.
        """

    # ── Like ──────────────────────────────────────────────────────────────────

    @abstractmethod
    def toggle_like(self, profile_id: int, article_id: UUID) -> bool:
        """
        Add a NewsLike row if none exists, or delete it if it does.
        Does not commit.
        Returns the new is_liked state (True = now liked, False = now unliked).
        """

    # ── Save ──────────────────────────────────────────────────────────────────

    @abstractmethod
    def toggle_save(self, profile_id: int, article_id: UUID) -> bool:
        """
        Add a NewsSave row if none exists, or delete it if it does.
        Does not commit.
        Returns the new is_saved state.
        """

    # ── Share ─────────────────────────────────────────────────────────────────

    @abstractmethod
    def record_share(
        self,
        profile_id: int,
        article_id: UUID,
        platform: str | None = None,
    ) -> None:
        """
        Append a NewsShare row.
        platform=None → in-app send; platform="whatsapp" etc. → external share.
        Does not commit — caller adjusts stats and commits together.
        """

    # ── Interaction events ────────────────────────────────────────────────────

    @abstractmethod
    def bulk_insert_events(self, events: list[NewsInteractionEvent]) -> None:
        """
        Bulk-insert a list of NewsInteractionEvent rows in one DB round-trip.
        Does not commit.
        """

    # ── Article stats ─────────────────────────────────────────────────────────

    @abstractmethod
    def get_article_stats(self, article_id: UUID) -> NewsArticleStats | None:
        """Return the pre-computed stats row for this article, or None."""

    @abstractmethod
    def adjust_article_stats(
        self,
        article_id: UUID,
        field: str,
        delta: int,
    ) -> None:
        """
        Increment or decrement one counter on NewsArticleStats.
        Creates the row with all-zero counters if it does not exist yet.
        field ∈ {"view_count", "like_count", "save_count", "share_count"}.
        Does not commit.
        """

    # ── Single entity reads ───────────────────────────────────────────────────
    # Used by application use cases that need full entity context (detail view,
    # taste updates). Recommendation layer accesses ORM directly — not used there.

    @abstractmethod
    def get_raw_article(self, article_id: UUID) -> RawArticle | None:
        """Return the full RawArticle entity, or None if not found."""

    @abstractmethod
    def get_enriched_article(self, article_id: UUID) -> EnrichedArticle | None:
        """Return the full EnrichedArticle for this raw article_id, or None."""

    @abstractmethod
    def get_like_state(self, profile_id: int, article_id: UUID) -> bool:
        """Return True if this profile has liked this article."""

    @abstractmethod
    def get_save_state(self, profile_id: int, article_id: UUID) -> bool:
        """Return True if this profile has saved this article."""

    # ── Taste ─────────────────────────────────────────────────────────────────
    # Used by the application layer when it needs to write taste signals
    # directly (e.g. process_interaction_batch → revisit event).
    # The recommendation/taste_service.py accesses the ORM directly for
    # its own reads; these methods serve the application layer only.

    @abstractmethod
    def upsert_taste(
        self,
        profile_id: int,
        dimension_type: str,
        dimension_key: str,
        positive_delta: float,
        negative_delta: float = 0.0,
        event_count: int = 1,
    ) -> None:
        """
        Atomic upsert of one UserNewsTaste row (ON CONFLICT DO UPDATE).
        Does not commit — the interaction use case commits the whole batch.
        """

    # ── Feed ranking cache ────────────────────────────────────────────────────

    @abstractmethod
    def get_feed_ranking_cache(
        self,
        profile_id: int,
        feed_type: str = "default",
    ) -> FeedRankingCache | None:
        """Return a non-expired cache row, or None if cache miss / expired."""

    @abstractmethod
    def upsert_feed_ranking_cache(
        self,
        profile_id: int,
        ranked_article_ids: list[UUID],
        feed_type: str = "default",
    ) -> None:
        """Write or replace the cache row. Commits."""

    @abstractmethod
    def invalidate_feed_ranking_cache(
        self,
        profile_id: int,
        feed_type: str = "default",
    ) -> None:
        """Delete the cache row if it exists. Commits."""
