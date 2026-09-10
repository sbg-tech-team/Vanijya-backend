"""
Domain value objects — enums and typed constants that define the vocabulary
of the news module. No infrastructure imports.
"""
from __future__ import annotations

from enum import Enum


class IntelligenceStatus(str, Enum):
    """Lifecycle state of a RawArticle through the enrichment pipeline."""
    PENDING    = "pending"
    PROCESSING = "processing"
    ENRICHED   = "enriched"
    FAILED     = "failed"


class GeoCategory(str, Enum):
    """Broad geographic scope of an article's subject matter."""
    GLOBAL   = "global"
    DOMESTIC = "domestic"


class ImpactDirection(str, Enum):
    """Market sentiment direction produced by the enrichment LLM."""
    POSITIVE = "positive"
    NEUTRAL  = "neutral"
    NEGATIVE = "negative"


# ── Interaction event types ───────────────────────────────────────────────────

# Events the client is allowed to submit in a batch.
CLIENT_EVENT_TYPES: frozenset[str] = frozenset({
    "impression",    # article card rendered in the feed
    "dwell",         # user spent time viewing (requires value_ms)
    "open_article",  # user tapped to open the full article
    "share_tap",     # user tapped the share / send button
})

# Events the server generates internally — never accepted from the client.
SERVER_EVENT_TYPES: frozenset[str] = frozenset({
    "revisit",       # user opened an article they had already opened before
})

ALL_EVENT_TYPES: frozenset[str] = CLIENT_EVENT_TYPES | SERVER_EVENT_TYPES
