# ---------------------------------------------------------------------------
# Domain constants re-exported from post_user_interaction so that existing
# imports inside this module stay unchanged.
# ---------------------------------------------------------------------------
from app.modules.post.post_user_interaction.constants import (   # noqa: F401
    CATEGORY_NAMES,
    COMMODITY_ID_TO_IDX,
    ROLE_ID_TO_IDX,
    TASTE_BOOTSTRAP_EVENTS,
)

# ---------------------------------------------------------------------------
# Category expiry (days a post stays in the recommendation index)
# ---------------------------------------------------------------------------
CATEGORY_EXPIRY_DAYS: dict[str, int] = {
    "market_update": 2,
    "deal_req": 7,
    "discussion": 14,
    "knowledge": 90,
}

# ---------------------------------------------------------------------------
# Partition time boundaries (hours since post creation)
# ---------------------------------------------------------------------------
HOT_MAX_HOURS  = 72    # 0 – 3 days
WARM_MAX_HOURS = 120   # 3 – 5 days
COLD_MAX_HOURS = 720   # 5 – 30 days

# Categories allowed in each partition (market_update expires before reaching warm)
PARTITION_ALLOWED: dict[str, set[str]] = {
    "hot":  {"market_update", "deal_req", "knowledge", "discussion"},
    "warm": {"deal_req", "knowledge", "discussion"},
    "cold": {"knowledge", "discussion"},
}

# ---------------------------------------------------------------------------
# Post feed vector layout: 10 dims
# [0:3] commodity  [3:6] role  [6:9] geo  [9] qty
# ---------------------------------------------------------------------------
VECTOR_DIM = 10

# Weights applied before cosine similarity (commodity dominates, qty is soft)
FEED_WEIGHTS = [3.0, 3.0, 3.0,   # commodity dims 0-2
                2.0, 2.0, 2.0,   # role dims 3-5
                1.5, 1.5, 1.5,   # geo dims 6-8
                1.0]             # qty dim 9

# Quantity normalisation scale (covers 99 % of platform trades)
QTY_SCALE_MT = 5000.0

# ---------------------------------------------------------------------------
# Feed retrieval thresholds
# ---------------------------------------------------------------------------
MIN_POOL_SIZE  = 80    # skip next partition if we already have this many candidates
FETCH_TARGET   = 150   # max candidates fetched per partition
FEED_SIZE      = 25    # final posts returned to caller
POPULAR_LIMIT  = 30    # popular posts appended to pool every feed load

# Diversity caps applied after reranking
MAX_PER_CATEGORY = 8
MAX_PER_AUTHOR   = 3

# ---------------------------------------------------------------------------
# Freshness
# Boost: 1.0 + FRESH_BOOST_PEAK × exp(-age_h / FRESH_DECAY_TAU)
# Peak at age=0 is (1.0 + FRESH_BOOST_PEAK). Fades to ~1.0 by 48 h.
# ---------------------------------------------------------------------------
FRESH_BOOST_PEAK = 0.4   # max additive boost above 1.0
FRESH_DECAY_TAU  = 8.0   # decay constant in hours (~5.5 h half-life)

# Fresh pool guarantee — posts younger than this are added to the candidate
# pool even when the ANN search would not naturally surface them.
FRESH_INJECT_HOURS = 4
FRESH_SLOTS        = 5   # max fresh candidates injected per feed call
