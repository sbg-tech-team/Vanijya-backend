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

# Trending job
TRENDING_LOOKBACK_H = 6       # hours of interactions to score
TRENDING_MIN_UNIQUE_USERS = 2 # minimum distinct profiles for an article to appear in trending

# Exponential decay lambda (~30-day half-life): ln(2) / 30
import math as _math
TASTE_DECAY_LAMBDA: float = _math.log(2) / 30

# Default taste seeding per role (1=Trader, 2=Broker, 3=Exporter).
# Derived from RELEVANCY_MATRIX in config so roles and matrix stay in sync.
from app.modules.news_new.config import RELEVANCY_MATRIX as _MATRIX
DEFAULT_TASTE: dict[int, dict[str, float]] = {
    role_id: {factor: _MATRIX[factor][role_name] for factor in _MATRIX}
    for role_id, role_name in ((1, "trader"), (2, "broker"), (3, "exporter"))
}
