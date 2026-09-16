"""
News recommendation engine.

Ranking pipeline (inline computation, no per-article persisted scores):

  Layer 1 — Role score
      role_score = enriched.role_trader | role_broker | role_exporter
      (column selected by profile's role_id)

  Layer 2 — Profile boost
      profile_boost = 0.25 x Jaccard(article_commodity_tags, profile_interests)
                    + 0.10 x binary(profile_home_state in article_state_tags)

  Layer 3 — Session-taste amplify (commodity + city + state, blended
      persistent + global-session + module-session via app.recommendation.amplify).
      Silent no-op on any Redis/DB failure.

  final_score = role_score x (1 + profile_boost) x commodity_boost x city_boost x state_boost

Candidate pool is time-bucketed: try 12h -> 24h -> 48h until MIN_POOL_SIZE reached.
Accesses data/models.py ORM directly per recommendation layer rules (ported
verbatim from app_v1_backup/modules/news_new/feed/service.py).
"""
from __future__ import annotations

import logging

from datetime import datetime, timedelta, timezone
from uuid import UUID

import redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.news.data.models import (
    EnrichedArticle,
    NewsSave,
    NewsTrending,
    RawArticle,
)
from app.modules.news.domain.value_objects import IntelligenceStatus
from app.modules.news.recommendation.constants import (
    BUCKET_HOURS,
    MIN_POOL_SIZE,
    RECENCY_POOL_CAP,
    TRENDING_POOL_CAP,
)
from app.modules.news.recommendation.profile_scorer import compute_profile_boost
from app.recommendation.amplify import (
    commodity_boost as _commodity_boost,
    commodity_ids_for,
    get_amplify_weights,
    location_boost as _location_boost,
)

log = logging.getLogger(__name__)

_ROLE_COL = {1: "role_trader", 2: "role_broker", 3: "role_exporter"}
_MODULE = "news"


class NewsRecommendationEngine:

    def __init__(self, db: Session) -> None:
        self._db = db

    def rank_feed(
        self,
        profile_id: int,
        role_id: int,
        commodity_interests: list[str],
        home_state: str | None,
        rc: redis.Redis | None = None,
    ) -> list[UUID]:
        """
        Return article IDs ranked by final_score (highest first).
        Caller (get_feed use case) stores in FeedRankingCache.
        """
        candidates = self._get_candidate_pool()
        if not candidates:
            return []

        role_col = _ROLE_COL.get(role_id, "role_trader")

        # Session-taste blend (Mechanism 1 - amplify). Silent fallback to
        # unboosted scoring on any Redis/DB failure.
        commodity_weights: dict[str, float] = {}
        city_weights: dict[str, float] = {}
        state_weights: dict[str, float] = {}
        if rc is not None:
            try:
                commodity_weights = get_amplify_weights(self._db, rc, profile_id, _MODULE, "commodity")
                city_weights = get_amplify_weights(self._db, rc, profile_id, _MODULE, "city")
                state_weights = get_amplify_weights(self._db, rc, profile_id, _MODULE, "state")
            except Exception:
                log.exception("amplify weights unavailable for profile %s; ranking without them", profile_id)

        scored: list[tuple[UUID, float]] = []

        for raw_id, enriched in candidates:
            if enriched is None:
                continue
            role_score = float(getattr(enriched, role_col, 0.0))
            profile_boost = compute_profile_boost(
                commodity_tags=enriched.commodity_tags,
                state_tags=enriched.state_tags,
                profile_commodity_interests=commodity_interests,
                profile_home_state=home_state,
            )
            base_score = role_score * (1 + profile_boost)

            session_boost = 1.0
            city_boost = 1.0
            state_boost = 1.0
            if commodity_weights:
                session_boost = _commodity_boost(
                    commodity_weights,
                    commodity_ids_for(self._db, enriched.commodity_tags or []),
                )
            if city_weights and enriched.location_city:
                city_boost = _location_boost(city_weights, [enriched.location_city])
            if state_weights and enriched.location_state:
                state_boost = _location_boost(state_weights, [enriched.location_state])

            final = base_score * session_boost * city_boost * state_boost
            scored.append((raw_id, final))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [article_id for article_id, _ in scored]

    def get_trending_ids(self) -> list[UUID]:
        """
        Merges two pools, velocity-first:
          1. Velocity pool (cap 100) - NewsTrending articles by velocity_score DESC
          2. Recency pool  (cap 50)  - latest enriched articles not in pool 1,
             by platform_arrived_at DESC
        No profile scoring or taste filtering.
        """
        velocity_ids = list(
            self._db.execute(
                select(RawArticle.id)
                .join(NewsTrending, NewsTrending.article_id == RawArticle.id)
                .where(RawArticle.is_active.is_(True), NewsTrending.velocity_score > 0)
                .order_by(NewsTrending.velocity_score.desc(), RawArticle.platform_arrived_at.desc())
                .limit(TRENDING_POOL_CAP)
            ).scalars()
        )

        recency_q = (
            select(RawArticle.id)
            .where(
                RawArticle.is_active.is_(True),
                RawArticle.intelligence_status == IntelligenceStatus.ENRICHED.value,
            )
            .order_by(RawArticle.platform_arrived_at.desc())
            .limit(RECENCY_POOL_CAP)
        )
        if velocity_ids:
            recency_q = recency_q.where(~RawArticle.id.in_(velocity_ids))

        recency_ids = list(self._db.execute(recency_q).scalars())

        return velocity_ids + recency_ids

    def get_saved_ids(self, profile_id: int) -> list[UUID]:
        """Article ids the profile has saved, most-recently-saved first."""
        return list(
            self._db.execute(
                select(NewsSave.article_id)
                .where(NewsSave.profile_id == profile_id)
                .order_by(NewsSave.created_at.desc())
            ).scalars()
        )

    def get_filtered_ids(self, feed_filter: str) -> list[UUID]:
        """
        Pure DB filter for global/domestic/government tabs - no recommendation,
        no scoring.
          - "global" / "domestic" -> geo_category match
          - "government"          -> is_government = True (any geo)
        Ordered by platform_arrived_at DESC.
        """
        if feed_filter == "government":
            enriched_ids_q = select(EnrichedArticle.raw_article_id).where(
                EnrichedArticle.is_government.is_(True)
            )
        else:
            enriched_ids_q = select(EnrichedArticle.raw_article_id).where(
                EnrichedArticle.geo_category == feed_filter
            )
        filtered_ids = list(self._db.execute(enriched_ids_q).scalars())
        if not filtered_ids:
            return []

        return list(
            self._db.execute(
                select(RawArticle.id)
                .where(RawArticle.is_active.is_(True), RawArticle.id.in_(filtered_ids))
                .order_by(RawArticle.platform_arrived_at.desc(), RawArticle.id.desc())
            ).scalars()
        )

    # -- Candidate pool ------------------------------------------------------

    def _get_candidate_pool(
        self,
    ) -> list[tuple[UUID, EnrichedArticle | None]]:
        """
        Time-bucketed candidate fetch: try buckets in order until MIN_POOL_SIZE.
        Returns list of (raw_article_id, enriched_article | None).
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        for hours in BUCKET_HOURS:
            cutoff = now - timedelta(hours=hours)
            rows = self._db.execute(
                select(RawArticle.id, EnrichedArticle)
                .outerjoin(
                    EnrichedArticle,
                    EnrichedArticle.raw_article_id == RawArticle.id,
                )
                .where(
                    RawArticle.is_active.is_(True),
                    RawArticle.is_duplicate.is_(False),
                    RawArticle.intelligence_status == IntelligenceStatus.ENRICHED.value,
                    RawArticle.platform_arrived_at >= cutoff,
                )
                .order_by(RawArticle.platform_arrived_at.desc())
                .limit(TRENDING_POOL_CAP + RECENCY_POOL_CAP)
            ).all()

            if len(rows) >= MIN_POOL_SIZE:
                return [(row[0], row[1]) for row in rows]

        return []
