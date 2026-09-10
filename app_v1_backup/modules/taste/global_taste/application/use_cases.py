"""
Global taste use cases — application layer.

Imports from domain/ interfaces only. Never imports from data/.

PromoteFromGlobalSession is the nightly promotion job logic.
It runs at 3am IST, driven by the scheduler in the calling module.
"""
from __future__ import annotations

from app.modules.taste.session_taste import (
    PROMOTION_CONFIDENCE_GATE,
    PROMOTION_EVENT_GATE,
    PROMOTION_FACTOR,
    PROMOTION_QUALITY_GATE,
    global_city_threshold,
    global_commodity_threshold,
    global_state_threshold,
)
from app.modules.taste.global_session.domain.interfaces import IGlobalSessionRepository
from app.modules.taste.global_taste.domain.entities import GlobalTasteScore, PromotionCandidate
from app.modules.taste.global_taste.domain.interfaces import IGlobalTasteRepository

# Dimension types with promotion logic decided. trade_intent is recognized by
# the sync/storage layer (CROSS_PLATFORM_DIMS) but has no promotion formula
# yet -- if it ever has data, it's silently skipped below until that's designed.
_PROMOTION_THRESHOLD_FNS = {
    "commodity": global_commodity_threshold,
    "city": global_city_threshold,
    "state": global_state_threshold,
}


class ReadGlobalTasteWeights:
    """Return decay-adjusted global taste weights for one dimension."""

    def __init__(self, repo: IGlobalTasteRepository) -> None:
        self._repo = repo

    def execute(
        self,
        profile_id: int,
        dimension_type: str,
    ) -> dict[str, float]:
        return self._repo.get_weights(profile_id, dimension_type)


class PromoteFromGlobalSession:
    """
    Nightly promotion: Global Session → Persistent Global Taste.

    Loops over every dimension type present in the user's global session
    (commodity, city, state -- whichever recognized types have data;
    trade_intent is silently skipped, no promotion logic decided yet). For
    each dimension key that passes all three gates:
        Gate 1 — confidence_gate: conf_score >= 0.70 × threshold
        Gate 2 — quality_gate:    weighted_taste_score >= 20
        Gate 3 — event_gate:      meaningful_events (conf > 0) >= 10

    Promotion formula:
        global_delta = pos_score - (neg_score × 0.6)
        persistent   += 0.15 × global_delta

    Safety order:
        1. Write qualifying deltas to PostgreSQL  (commit first)
        2. Clear global session from Redis        (only after DB confirms)

    This use case returns the list of PromotionCandidates found.
    The caller is responsible for committing the DB session and clearing Redis.
    """

    def __init__(
        self,
        global_session_repo: IGlobalSessionRepository,
        global_taste_repo: IGlobalTasteRepository,
    ) -> None:
        self._gs = global_session_repo
        self._gt = global_taste_repo

    def execute(self, profile_id: int) -> list[PromotionCandidate]:
        all_data = self._gs.read_all_dimension_data(profile_id)
        if not all_data:
            return []

        candidates: list[PromotionCandidate] = []

        for dimension_type, raw_data in all_data.items():
            threshold_fn = _PROMOTION_THRESHOLD_FNS.get(dimension_type)
            if threshold_fn is None:
                continue  # e.g. trade_intent -- recognized by sync, not by promotion yet

            for dkey, data in raw_data.items():
                pos  = data.get("pos", 0.0)
                neg  = data.get("neg", 0.0)
                conf = data.get("conf", 0.0)
                cnt  = int(data.get("cnt", 0))

                # Get current persistent score for threshold scaling
                existing = self._gt.get_score(profile_id, dimension_type, dkey)
                pers_score = existing.positive_score if existing else 0.0

                threshold = threshold_fn(pers_score)

                # Gate 1: confidence
                if conf < PROMOTION_CONFIDENCE_GATE * threshold:
                    continue

                # Gate 2: quality (weighted taste)
                quality = pos - (neg * 0.6)
                if quality < PROMOTION_QUALITY_GATE:
                    continue

                # Gate 3: events (meaningful = any event that contributed conf)
                if cnt < PROMOTION_EVENT_GATE:
                    continue

                global_delta = pos - (neg * 0.6)
                promotion_delta = PROMOTION_FACTOR * global_delta

                if promotion_delta <= 0:
                    continue

                candidates.append(PromotionCandidate(
                    profile_id=profile_id,
                    dimension_type=dimension_type,
                    dimension_key=dkey,
                    delta=promotion_delta,
                ))

        # Bulk-write all qualifying deltas
        if candidates:
            self._gt.bulk_apply_promotion([
                (c.profile_id, c.dimension_type, c.dimension_key, c.delta)
                for c in candidates
            ])

        return candidates
