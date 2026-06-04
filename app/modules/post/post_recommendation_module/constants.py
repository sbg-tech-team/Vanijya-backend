# ---------------------------------------------------------------------------
# Category mapping (must match post_categories seed: 1=Market Update,
# 2=Knowledge, 3=Discussion, 4=Deal/Req)
# ---------------------------------------------------------------------------
CATEGORY_NAMES: dict[int, str] = {
    1: "market_update",
    2: "knowledge",
    3: "discussion",
    4: "deal_req",
}

CATEGORY_EXPIRY_DAYS: dict[str, int] = {
    "market_update": 2,
    "deal_req": 7,
    "discussion": 14,
    "knowledge": 90,
}

# ---------------------------------------------------------------------------
# Partition time boundaries (hours since post creation)
# ---------------------------------------------------------------------------
HOT_MAX_HOURS = 72       # 0 – 3 days
WARM_MAX_HOURS = 120     # 3 – 5 days
COLD_MAX_HOURS = 720     # 5 – 30 days

# Categories allowed in each partition (market_update expires before reaching warm)
PARTITION_ALLOWED: dict[str, set[str]] = {
    "hot":  {"market_update", "deal_req", "knowledge", "discussion"},
    "warm": {"deal_req", "knowledge", "discussion"},
    "cold": {"knowledge", "discussion"},
}

# ---------------------------------------------------------------------------
# Vector layout: 10 dims
# [0:3] commodity  [3:6] role  [6:9] geo  [9] qty
# ---------------------------------------------------------------------------
VECTOR_DIM = 10

# Weights applied before cosine similarity (commodity dominates, qty is soft)
FEED_WEIGHTS = [3.0, 3.0, 3.0,   # commodity dims 0-2
                2.0, 2.0, 2.0,   # role dims 3-5
                1.5, 1.5, 1.5,   # geo dims 6-8
                1.0]             # qty dim 9

# ---------------------------------------------------------------------------
# Commodity ID → vector index
# DB seed: 1=Rice  2=Cotton  3=Sugar
# Vector order (matches weights_config ALL_COMMODITIES): cotton=0, rice=1, sugar=2
# ---------------------------------------------------------------------------
COMMODITY_ID_TO_IDX: dict[int, int] = {1: 1, 2: 0, 3: 2}

# ---------------------------------------------------------------------------
# Role ID → index within the role block (offset 3)
# DB seed: 1=Trader  2=Broker  3=Exporter
# PDF vector order: trader=0, exporter=1, broker=2
# ---------------------------------------------------------------------------
ROLE_ID_TO_IDX: dict[int, int] = {1: 0, 2: 2, 3: 1}

# Quantity normalisation scale (covers 99% of platform trades)
QTY_SCALE_MT = 5000.0

# ---------------------------------------------------------------------------
# Default taste profiles seeded by role (used until 20 interactions logged)
# ---------------------------------------------------------------------------
DEFAULT_TASTE: dict[int, dict[str, int]] = {
    1: {"deal_req": 100, "market_update": 80, "discussion": 20, "knowledge": 20},
    2: {"deal_req": 100, "market_update": 60, "discussion": 50, "knowledge": 30},
    3: {"deal_req": 60,  "market_update": 100, "knowledge": 50, "discussion": 20},
}

# ---------------------------------------------------------------------------
# Feed retrieval thresholds
# ---------------------------------------------------------------------------
MIN_POOL_SIZE = 80       # skip next partition if we already have this many candidates
FETCH_TARGET = 150       # max candidates fetched per partition
FEED_SIZE = 25           # final posts returned to caller
POPULAR_LIMIT = 30       # popular posts appended to pool every feed load

# Diversity caps applied at the end
MAX_PER_CATEGORY = 8
MAX_PER_AUTHOR = 3

# Taste interaction threshold before behavioural layer kicks in
TASTE_BOOTSTRAP_EVENTS = 20

# ---------------------------------------------------------------------------
# Freshness
# Boost decays continuously: 1.0 + FRESH_BOOST_PEAK * exp(-age_h / FRESH_DECAY_TAU)
# Peak boost at age=0 is (1.0 + FRESH_BOOST_PEAK). Fades to ~1.0 by 48h.
# FRESH_DECAY_TAU controls the half-life (~5.5h with tau=8).
# ---------------------------------------------------------------------------
FRESH_BOOST_PEAK = 0.4   # max additive boost above 1.0
FRESH_DECAY_TAU  = 8.0   # decay constant in hours

# Fresh pool guarantee — posts younger than this are added to the candidate pool
# even if the ANN search wouldn't naturally surface them (e.g. > FETCH_TARGET hot posts).
FRESH_INJECT_HOURS = 4
FRESH_SLOTS        = 5   # max fresh candidates injected into pool
