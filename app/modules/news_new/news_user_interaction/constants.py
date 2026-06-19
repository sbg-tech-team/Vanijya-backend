# Client-submitted event types
VALID_CLIENT_EVENT_TYPES = frozenset({
    "impression",    # article card shown to user in feed
    "dwell",         # user spent time on article (requires value_ms)
    "open_article",  # user opened the article detail view
    "share_tap",     # user tapped share button
})

# Server-generated (not accepted from client)
SERVER_EVENT_TYPES = frozenset({"revisit"})

ALL_EVENT_TYPES = VALID_CLIENT_EVENT_TYPES | SERVER_EVENT_TYPES

# Dwell thresholds (milliseconds) — calibrate for news reading patterns
DWELL_BOUNCE_MS = 3_000       # < 3s  → bounce (negative signal)
DWELL_SHORT_MS = 15_000       # 3–15s → short
DWELL_MEDIUM_MS = 60_000      # 15–60s → medium
# >= 60s → long

DWELL_SEEN_MS = 5_000         # >= 5s marks article as seen
DWELL_VALUE_CAP_MS = 600_000  # 10 min server-side cap
MAX_EVENT_AGE_HOURS = 2       # events older than 2h are dropped

# Signal weights: (positive_delta, negative_delta)
# Keyed by event type; dwell events are classified first
SIGNAL_WEIGHTS: dict[str, tuple[float, float]] = {
    "impression":     (0.1, 0.0),
    "dwell_bounce":   (0.0, 0.5),
    "dwell_short":    (0.5, 0.0),
    "dwell_medium":   (2.0, 0.0),
    "dwell_long":     (3.5, 0.0),
    "open_article":   (1.5, 0.0),
    "share_tap":      (2.0, 0.0),
    # Synchronous signals
    "like":           (3.0, 0.0),
    "save":           (5.0, 0.0),
    "share":          (4.0, 0.0),
    "revisit":        (6.0, 0.0),
}

# Taste dimensions
TASTE_DIMENSIONS = frozenset({"category", "source", "tag"})

# Minimum events before taste profile is considered bootstrapped
TASTE_BOOTSTRAP_EVENTS = 20
