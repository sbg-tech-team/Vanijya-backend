"""
Layer 2: profile boost scorer.

profile_boost = PROFILE_BOOST_COMMODITY × Jaccard(article_commodity_tags, profile_interests)
              + PROFILE_BOOST_STATE     × binary(profile_home_state ∈ article_state_tags)

Used inline in engine.rank_feed() — not stored between requests.
"""
from __future__ import annotations

from app.modules.news.recommendation.constants import (
    PROFILE_BOOST_COMMODITY,
    PROFILE_BOOST_STATE,
)


def compute_profile_boost(
    commodity_tags: list[str] | None,
    state_tags: list[str] | None,
    profile_commodity_interests: list[str],
    profile_home_state: str | None,
) -> float:
    commodity_boost = _jaccard(
        set(t.lower() for t in (commodity_tags or [])),
        set(t.lower() for t in profile_commodity_interests),
    )
    state_match = (
        bool(state_tags)
        and bool(profile_home_state)
        and profile_home_state.lower() in {s.lower() for s in state_tags}
    )
    state_boost = 1.0 if state_match else 0.0
    return PROFILE_BOOST_COMMODITY * commodity_boost + PROFILE_BOOST_STATE * state_boost


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)
