"""
Home Feed Domain Entities — pure Python, no framework dependencies.

These dataclasses represent the core business objects of the home feed domain.
They are intentionally decoupled from SQLAlchemy, Pydantic, FastAPI, and Redis.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.modules.home_feed.domain.value_objects import (
    ActionType,
    ContentTypeLabel,
    FeedItemType,
)


# ── Feed Cursor ────────────────────────────────────────────────────────────────

@dataclass
class FeedCursor:
    """
    Opaque pagination token passed back to the client.
    The feed uses page-based pagination; each source pipeline advances by page.
    """
    page_num: int = 1


# ── Feed Item ──────────────────────────────────────────────────────────────────

@dataclass
class FeedItem:
    """
    A single card in the home feed.

    item_type            : the content category (post / news / group / connection)
    item_id              : string key that identifies the underlying resource
    data                 : raw payload forwarded to the client as-is
    is_priority          : True for breaking-news pins placed at the top / interleaved
    content_type_label   : human-readable sub-label (e.g. "breaking_news",
                           "group_suggestion") used by the client for rendering
    """
    item_type: FeedItemType
    item_id: str
    data: Dict[str, Any]
    is_priority: bool = False
    content_type_label: ContentTypeLabel = ContentTypeLabel.POST


# ── Feed Page ──────────────────────────────────────────────────────────────────

@dataclass
class FeedPage:
    """
    One page of the home feed as returned by the use-case layer.

    items        : ordered list of mixed feed cards
    cursor       : cursor to pass for the next page request
    has_more     : False when all source pools are exhausted
    weights_used : the type-mix weights actually applied by the mixer (debug info)
    """
    items: List[FeedItem]
    cursor: FeedCursor
    has_more: bool
    weights_used: Optional[Dict[str, float]] = None


# ── Engagement Signal ──────────────────────────────────────────────────────────

@dataclass
class EngagementSignal:
    """
    A single user-interaction event captured on the client and batched to the
    backend.  dwell_ms is populated for dwell / strong_dwell / skip actions.
    """
    item_id: str
    item_type: FeedItemType
    action: ActionType
    dwell_ms: Optional[int] = None      # ms; present for dwell/strong_dwell/skip


# ── Engagement Batch ──────────────────────────────────────────────────────────

@dataclass
class EngagementBatch:
    """
    A batch of engagement signals submitted by the client in a single request.
    The optional cursor is included so the backend can correlate signals with
    the page they originated from.
    """
    signals: List[EngagementSignal] = field(default_factory=list)
    cursor: Optional[FeedCursor] = None


# ── Session Taste ─────────────────────────────────────────────────────────────

@dataclass
class ContentTypeTasteBlock:
    """
    Per-content-type engagement counters that form one slice of the session taste.
    """
    dwells: int = 0
    likes: int = 0
    saves: int = 0
    skips: int = 0
    shares: int = 0
    comments: int = 0
    accepts: int = 0          # connection_accept
    dismisses: int = 0        # connection_dismiss
    total_dwell_ms: int = 0


@dataclass
class SessionTaste:
    """
    Ephemeral, in-session engagement profile for a user.

    Stored in Redis (TTL 2 h) and used to blend per-page default type-mix
    weights with observed engagement.  At cold-start all blocks are zero and
    blend_factor evaluates to 0.0 so page defaults are used unchanged.
    """
    profile_id: int
    session_id: str
    post: ContentTypeTasteBlock = field(default_factory=ContentTypeTasteBlock)
    news: ContentTypeTasteBlock = field(default_factory=ContentTypeTasteBlock)
    group: ContentTypeTasteBlock = field(default_factory=ContentTypeTasteBlock)
    connection: ContentTypeTasteBlock = field(default_factory=ContentTypeTasteBlock)
    items_seen: int = 0
    last_updated_at: Optional[datetime] = None


# ── Feed Source Candidate Pool ────────────────────────────────────────────────

@dataclass
class CandidatePool:
    """
    The raw candidate lists fetched from each source pipeline before mixing.

    posts       : personalised post cards
    news        : regular news cards (breaking items are separated out)
    groups      : group-join suggestions
    connections : people-you-may-know suggestions
    breaking    : high-priority news pins prepended / interleaved on first load
    """
    posts: List[FeedItem] = field(default_factory=list)
    news: List[FeedItem] = field(default_factory=list)
    groups: List[FeedItem] = field(default_factory=list)
    connections: List[FeedItem] = field(default_factory=list)
    breaking: List[FeedItem] = field(default_factory=list)

    def as_dict(self) -> Dict[str, List[FeedItem]]:
        """Map content-type keys to their candidate lists (for the mixer)."""
        return {
            "post": self.posts,
            "news": self.news,
            "group": self.groups,
            "connection": self.connections,
        }

    def is_empty(self) -> bool:
        return not any([self.posts, self.news, self.groups, self.connections])


# ── Feed Mix Weights ──────────────────────────────────────────────────────────

@dataclass
class FeedWeights:
    """
    Normalised type-mix weights applied by the weighted-random mixer.

    All four weights must be non-negative; the mixer normalises them to sum 1.0
    internally.  Defaults reflect the static cold-start ratio.
    """
    post: float = 0.45
    news: float = 0.25
    group: float = 0.15
    connection: float = 0.15

    def as_dict(self) -> Dict[str, float]:
        return {
            "post": self.post,
            "news": self.news,
            "group": self.group,
            "connection": self.connection,
        }
