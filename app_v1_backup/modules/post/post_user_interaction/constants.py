# ---------------------------------------------------------------------------
# Domain mappings (shared with post_recommendation_module via re-export)
# ---------------------------------------------------------------------------

# Category ID → name (must match post_categories seed data)
# 1=Market Update  2=Knowledge  3=Discussion  4=Deal/Req
CATEGORY_NAMES: dict[int, str] = {
    1: "market_update",
    2: "knowledge",
    3: "discussion",
    4: "deal_req",
}

# Commodity DB id → vector index
# DB seed: 1=Rice  2=Cotton  3=Sugar
# Vector order: cotton=0, rice=1, sugar=2
COMMODITY_ID_TO_IDX: dict[int, int] = {1: 1, 2: 0, 3: 2}

# Role DB id → vector index (offset 3 in the 10-dim post vector)
# DB seed: 1=Trader  2=Broker  3=Exporter
ROLE_ID_TO_IDX: dict[int, int] = {1: 0, 2: 2, 3: 1}

# ---------------------------------------------------------------------------
# Taste — cold-start defaults seeded by role
# Used until TASTE_BOOTSTRAP_EVENTS interactions are recorded.
# ---------------------------------------------------------------------------
DEFAULT_TASTE: dict[int, dict[str, int]] = {
    1: {"deal_req": 100, "market_update": 80,  "discussion": 20, "knowledge": 20},  # Trader
    2: {"deal_req": 100, "market_update": 60,  "discussion": 50, "knowledge": 30},  # Broker
    3: {"deal_req": 60,  "market_update": 100, "knowledge": 50,  "discussion": 20},  # Exporter
}

# Minimum interactions before the recommendation engine trusts learned taste
# over role-seeded defaults. Below this the system blends both.
TASTE_BOOTSTRAP_EVENTS = 20

# ---------------------------------------------------------------------------
# Interaction event types accepted by the batch endpoint
# "revisit" is server-generated and not accepted from the client, but
# included here so signal derivation logic can reference it uniformly.
# ---------------------------------------------------------------------------
VALID_CLIENT_EVENT_TYPES: frozenset[str] = frozenset({
    "impression",
    "dwell",
    "open_read_more",
    "open_carousel",
    "open_comments",
    "link_click",
})

ALL_EVENT_TYPES: frozenset[str] = VALID_CLIENT_EVENT_TYPES | {"revisit"}

# ---------------------------------------------------------------------------
# Dwell thresholds (milliseconds)
# ---------------------------------------------------------------------------
MAX_EVENT_AGE_HOURS = 2     # events older than this are silently dropped by the batch endpoint

DWELL_SEEN_MS   = 3_000     # >= marks post as seen (excluded from rec feed)
DWELL_BOUNCE_MS = 2_000     # <  classified as bounce (negative signal, Phase 5B)
DWELL_SHORT_MS  = 8_000     # 2 000–8 000 ms: short dwell
DWELL_LONG_MS   = 30_000    # >= 30 s: strong/long dwell
DWELL_VALUE_CAP_MS = 300_000  # 5 min — server-enforced ceiling on stored value

# ---------------------------------------------------------------------------
# Signal weights — (positive_delta, negative_delta) per classified event
# Used by Phase 2 signal derivation layer.
# ---------------------------------------------------------------------------
SIGNAL_WEIGHTS: dict[str, tuple[float, float]] = {
    "impression":      (0.1, 0.0),
    "dwell_bounce":    (0.0, 0.5),
    "dwell_short":     (0.5, 0.0),
    "dwell_medium":    (2.0, 0.0),
    "dwell_long":      (3.5, 0.0),
    "open_read_more":  (1.5, 0.0),
    "open_carousel":   (1.0, 0.0),
    "open_comments":   (1.5, 0.0),
    "link_click":      (2.0, 0.0),
    "like":            (3.0, 0.0),
    "save":            (5.0, 0.0),
    "share":           (4.0, 0.0),
    "comment":         (4.0, 0.0),
    "revisit":         (6.0, 0.0),
}

# ---------------------------------------------------------------------------
# Taste decay
# Query-time decay: decayed_score = raw_score × exp(-λ × days_since_last_event)
# λ = 0.023 → ~30-day half-life
# ---------------------------------------------------------------------------
TASTE_DECAY_LAMBDA = 0.023

# ---------------------------------------------------------------------------
# Author affinity
# Only signals with pos_delta >= AUTHOR_TASTE_MIN_DELTA write an author row.
# This filters out weak signals (impression=0.1, dwell_short=0.5) so author
# rows don't inflate from low-confidence events.
#
# Eligible signals (pos_delta >= 2.0):
#   like(3.0), save(5.0), comment(4.0), share(4.0), revisit(6.0),
#   dwell_medium(2.0), dwell_long(3.5)
# ---------------------------------------------------------------------------
AUTHOR_TASTE_MIN_DELTA  = 2.0    # minimum pos_delta to write an author taste row
AUTHOR_AFFINITY_MAX     = 1.2    # multiplier ceiling for non-followed authors
AUTHOR_AFFINITY_SATURATION = 20.0  # raw score at which multiplier reaches AUTHOR_AFFINITY_MAX

# ---------------------------------------------------------------------------
# Repeated-ignore detection (Phase 5)
# A post shown to a user N+ times with no engagement is an "ignored" post.
# The detection job applies a negative taste delta to the relevant category
# and commodity, then marks those impression events processed so the pair
# is only actioned once.
# ---------------------------------------------------------------------------
REPEATED_IGNORE_THRESHOLD = 5    # impressions without any open/dwell to trigger
IGNORE_NEG_DELTA          = 1.0  # negative_score delta per ignored post detected
