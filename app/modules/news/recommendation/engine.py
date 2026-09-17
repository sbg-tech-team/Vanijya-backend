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

    def __init__(self, repo) -> None:
        self._repo = repo

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
        candidates = self._repo.news_candidate_pool()
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
                commodity_weights = get_amplify_weights(self._repo.session, rc, profile_id, _MODULE, "commodity")
                city_weights = get_amplify_weights(self._repo.session, rc, profile_id, _MODULE, "city")
                state_weights = get_amplify_weights(self._repo.session, rc, profile_id, _MODULE, "state")
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
                    commodity_ids_for(self._repo.session, enriched.commodity_tags or []),
                )
            if city_weights and enriched.location_city:
                city_boost = _location_boost(city_weights, [enriched.location_city])
            if state_weights and enriched.location_state:
                state_boost = _location_boost(state_weights, [enriched.location_state])

            final = base_score * session_boost * city_boost * state_boost
            scored.append((raw_id, final))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [article_id for article_id, _ in scored]




    # -- Candidate pool ------------------------------------------------------

