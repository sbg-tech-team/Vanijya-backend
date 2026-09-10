"""
Get feed use case.

Supports six feed types:
  - "default"    - personalised ranked feed (Layer 1 + Layer 2 + session-taste amplify)
  - "trending"   - platform-wide trending (velocity pool + recency-pool fallback)
  - "saved"      - articles the profile has saved, most-recently-saved first
  - "global"     - geo_category == "global", recency ordered
  - "domestic"   - geo_category == "domestic", recency ordered
  - "government" - is_government == True (any geo), recency ordered

Cache strategy (default feed only, matching app_v1_backup which never cached
trending/saved/filtered):
  - Check FeedRankingCache (2h TTL) before computing "default".
  - Miss -> call recommendation engine -> store ranked IDs in cache.
  - Cache is invalidated on strong interaction signals (via record_interaction).

Pagination:
  - Flat cursor-based: `cursor_article_id` is the last article_id from the
    previous page. Pass None for the first page.
  - `next_cursor` is None when there are no more pages.

Card assembly:
  - For each article in the current page, fetch raw + enriched + stats + user
    state from the repository and build a NewsCard. Missing enriched fields
    are simply null on the card (article still shown) - only a missing raw
    article causes a skip.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

import redis

from app.modules.news.domain.entities import NewsFeedPage, NewsCard
from app.modules.news.domain.interfaces.repository import INewsRepository
from app.modules.news.recommendation.engine import NewsRecommendationEngine

log = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 50

_UNCACHED_FEED_TYPES = frozenset({"trending", "saved", "global", "domestic", "government"})
_GEO_FEED_TYPES = frozenset({"global", "domestic", "government"})


class GetFeedUseCase:

    def __init__(
        self,
        repo: INewsRepository,
        engine: NewsRecommendationEngine,
    ) -> None:
        self._repo = repo
        self._engine = engine

    def execute(
        self,
        profile_id: int,
        role_id: int,
        commodity_interests: list[str],
        home_state: str | None,
        feed_type: str = "default",
        cursor_article_id: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        rc: redis.Redis | None = None,
    ) -> NewsFeedPage:
        page_size = min(page_size, MAX_PAGE_SIZE)

        ranked_ids = self._get_ranked_ids(
            profile_id, role_id, commodity_interests, home_state, feed_type, rc
        )
        if not ranked_ids:
            return NewsFeedPage(articles=[], next_cursor=None)

        # Cursor pagination
        start_idx = 0
        if cursor_article_id:
            try:
                cursor_uuid = UUID(cursor_article_id)
                for i, aid in enumerate(ranked_ids):
                    if aid == cursor_uuid:
                        start_idx = i + 1
                        break
            except ValueError:
                pass

        page_ids = ranked_ids[start_idx : start_idx + page_size]
        next_cursor = (
            str(page_ids[-1])
            if page_ids and start_idx + page_size < len(ranked_ids)
            else None
        )

        # Assemble cards
        cards: list[NewsCard] = []
        for article_id in page_ids:
            card = self._assemble_card(profile_id, article_id)
            if card is not None:
                cards.append(card)

        return NewsFeedPage(articles=cards, next_cursor=next_cursor)

    # -- Ranking --------------------------------------------------------------

    def _get_ranked_ids(
        self,
        profile_id: int,
        role_id: int,
        commodity_interests: list[str],
        home_state: str | None,
        feed_type: str,
        rc: redis.Redis | None,
    ) -> list[UUID]:
        if feed_type in _UNCACHED_FEED_TYPES:
            if feed_type == "trending":
                return self._engine.get_trending_ids()
            if feed_type == "saved":
                return self._engine.get_saved_ids(profile_id)
            if feed_type in _GEO_FEED_TYPES:
                return self._engine.get_filtered_ids(feed_type)

        # "default" - cache check
        cached = self._repo.get_feed_ranking_cache(profile_id, feed_type)
        if cached is not None:
            return cached.ranked_article_ids

        ranked_ids = self._engine.rank_feed(
            profile_id=profile_id,
            role_id=role_id,
            commodity_interests=commodity_interests,
            home_state=home_state,
            rc=rc,
        )

        if ranked_ids:
            self._repo.upsert_feed_ranking_cache(profile_id, ranked_ids, feed_type)

        return ranked_ids

    # -- Card assembly ----------------------------------------------------------

    def _assemble_card(self, profile_id: int, article_id: UUID) -> NewsCard | None:
        raw = self._repo.get_raw_article(article_id)
        if raw is None:
            return None

        enriched = self._repo.get_enriched_article(article_id)
        stats = self._repo.get_article_stats(article_id)
        is_liked = self._repo.get_like_state(profile_id, article_id)
        is_saved = self._repo.get_save_state(profile_id, article_id)

        return NewsCard(
            article_id=raw.id,
            title=raw.title,
            platform_arrived_at=raw.platform_arrived_at,
            time_on_platform=_compute_time_on_platform(raw.platform_arrived_at),
            image_url=raw.image_url,
            source_name=raw.source_name,
            summary_bullets=enriched.summary_bullets if enriched else None,
            primary_factor=enriched.primary_factor if enriched else None,
            geo_category=enriched.geo_category if enriched else None,
            is_government=enriched.is_government if enriched else False,
            impact_direction=enriched.impact_direction if enriched else None,
            impact_score=enriched.impact_score if enriched else None,
            like_count=stats.like_count if stats else 0,
            share_count=stats.share_count if stats else 0,
            is_liked=is_liked,
            is_saved=is_saved,
        )


def _compute_time_on_platform(platform_arrived_at: datetime) -> str:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    arrived = platform_arrived_at.replace(tzinfo=None) if platform_arrived_at.tzinfo else platform_arrived_at
    delta = now - arrived
    hours = int(delta.total_seconds() / 3600)
    if hours < 24:
        return f"{max(1, hours)}h"
    days = delta.days
    if days == 1:
        return "Yesterday"
    return f"{days} days ago"
