"""
Constants for the recommendation and taste layers.

All values taken from V1's news_user_interaction/constants.py and config.py.
"""
from __future__ import annotations

import math

from app.modules.news.domain.constants import RELEVANCY_MATRIX

# ── Feed candidate pool ───────────────────────────────────────────────────────

BUCKET_HOURS: list[int] = [12, 24, 48]
MIN_POOL_SIZE: int = 30
TRENDING_POOL_CAP: int = 100
RECENCY_POOL_CAP: int = 50

# ── Layer 2: profile boost weights ───────────────────────────────────────────

PROFILE_BOOST_COMMODITY: float = 0.25
PROFILE_BOOST_STATE: float = 0.10

# ── Trending job ──────────────────────────────────────────────────────────────

TRENDING_LOOKBACK_H: int = 6
TRENDING_MIN_UNIQUE_USERS: int = 2

# ── Feed cache ────────────────────────────────────────────────────────────────

CACHE_TTL_HOURS: int = 2

# ── Taste model ───────────────────────────────────────────────────────────────

TASTE_DECAY_LAMBDA: float = math.log(2) / 30
TASTE_BOOTSTRAP_EVENTS: int = 20
TASTE_SCORE_FLOOR: float = 0.05
TASTE_NEG_DISCOUNT: float = 0.6

# ── Default taste seeds per role (1=Trader, 2=Broker, 3=Exporter) ─────────────
# Derived from RELEVANCY_MATRIX so roles and matrix stay in sync.

DEFAULT_TASTE: dict[int, dict[str, float]] = {
    role_id: {factor: RELEVANCY_MATRIX[factor][role_name] for factor in RELEVANCY_MATRIX}
    for role_id, role_name in ((1, "trader"), (2, "broker"), (3, "exporter"))
}
