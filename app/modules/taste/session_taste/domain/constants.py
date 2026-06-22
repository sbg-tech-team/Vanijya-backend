"""
Taste domain constants — single source of truth for all modules.

Covers: Post, News, Connections, Feed.
These constants drive signal ingestion, decay, confidence gating, and
the nightly promotion formula. They are pure Python and carry no I/O deps.
"""
from __future__ import annotations

# ── Decay ─────────────────────────────────────────────────────────────────────

TASTE_DECAY_LAMBDA: float = 0.023      # ~30-day half-life. Applied at read time.

# ── Session TTLs ──────────────────────────────────────────────────────────────

MODULE_SESSION_TTL: int = 7200         # 2 h inactivity — resets on every write
GLOBAL_SESSION_TTL: int = 86400        # 1 day — also explicitly cleared by nightly job

# ── Signal weights: (pos_delta, neg_delta, conf_delta) ───────────────────────
# One entry per ActionType value. Covers all four modules.

SIGNAL_WEIGHTS: dict[str, tuple[float, float, float]] = {
    # ── Passive / passive-implicit (post & news) ─────────────────────────────
    "impression":          (0.1, 0.0, 0.0),
    "view":                (0.0, 0.0, 0.1),
    "dwell_bounce":        (0.0, 0.5, 0.0),   # neg only; conf=0 (ambiguous)
    "dwell_short":         (0.5, 0.0, 0.2),
    "dwell_medium":        (2.0, 0.0, 0.5),
    "dwell_long":          (3.5, 0.0, 1.0),
    # ── Open events (post) ────────────────────────────────────────────────────
    "open_read_more":      (1.5, 0.0, 0.3),
    "open_carousel":       (1.0, 0.0, 0.2),
    "open_comments":       (1.5, 0.0, 0.3),
    "link_click":          (2.0, 0.0, 0.5),
    # ── Explicit (post & news) ────────────────────────────────────────────────
    "like":                (3.0, 0.0, 2.0),
    "save":                (5.0, 0.0, 4.0),
    "comment":             (4.0, 0.0, 5.0),
    "share":               (4.0, 0.0, 6.0),
    "revisit":             (6.0, 0.0, 4.0),
    # ── Connections module ────────────────────────────────────────────────────
    "connection_view":     (0.5, 0.0, 0.2),   # viewed a profile card
    "connection_accept":   (5.0, 0.0, 4.0),   # accepted a suggested connection
    "connection_dismiss":  (0.0, 2.0, 0.0),   # dismissed a suggestion (neg; conf=0)
    # ── Feed module ───────────────────────────────────────────────────────────
    "feed_skip":           (0.0, 1.0, 0.0),   # scrolled past without pause
    "feed_pause":          (1.0, 0.0, 0.3),   # brief pause (non-open dwell)
}

# ── Author write minimum ──────────────────────────────────────────────────────
# Only write author dimension when pos_delta reaches this threshold.
# Ensures noisy low-signal events don't pollute author affinity.

AUTHOR_MIN_TASTE_DELTA: float = 2.0

# ── Cross-platform dimensions ─────────────────────────────────────────────────
# Only these sync from module session → global session.
# location and quantity are placeholders; activate when their modules are built.

CROSS_PLATFORM_DIMS: frozenset[str] = frozenset({"commodity"})

# ── Confidence thresholds ─────────────────────────────────────────────────────

CATEGORY_CONF_THRESHOLD: float = 10.0        # flat for all categories
AUTHOR_SESSION_CONF_THRESHOLD: float = 6.0   # lower — binary per-author signal


def module_commodity_threshold(persistent_score: float) -> float:
    """
    Commodity confidence threshold for module session.
    Scales up with persistent score: established traders are harder to shift.
    """
    return 8.0 * (1.0 + persistent_score / 50.0)


def global_commodity_threshold(persistent_score: float) -> float:
    """
    Commodity confidence threshold for global session.
    Harder than module — cross-platform evidence requires more signal.
    """
    return 12.0 * (1.0 + persistent_score / 100.0)


# ── Influence caps (additive blend at weight-preparation level) ───────────────

MODULE_SESSION_MAX_INFLUENCE: float = 0.31
GLOBAL_SESSION_MAX_INFLUENCE: float = 0.15
PERSISTENT_MIN_INFLUENCE: float = 0.54    # = 1.0 - 0.31 - 0.15; never breached

# ── Nightly promotion gates (all three must pass per dimension) ───────────────

PROMOTION_CONFIDENCE_GATE: float = 0.70   # conf_score >= 70% of threshold
PROMOTION_QUALITY_GATE: float = 20.0      # weighted taste score floor
PROMOTION_EVENT_GATE: int = 10            # meaningful events (conf_delta > 0)
PROMOTION_FACTOR: float = 0.15           # persistent += 0.15 × global_delta
