"""
Home Feed Domain Value Objects — pure Python, no framework dependencies.

Enums and simple immutable value types used by the home feed domain entities.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


# ── Content / Item Type ───────────────────────────────────────────────────────

class FeedItemType(str, Enum):
    """The four first-class content categories that appear in the home feed."""
    POST = "post"
    NEWS = "news"
    GROUP = "group"
    CONNECTION = "connection"


# ── Content Type Label ────────────────────────────────────────────────────────

class ContentTypeLabel(str, Enum):
    """
    Human-readable sub-label attached to each FeedItem.
    Used by the client for card-level rendering decisions.
    """
    POST = "post"
    NEWS = "news"
    BREAKING_NEWS = "breaking_news"
    GROUP_SUGGESTION = "group_suggestion"
    CONNECTION = "connection"


# ── Engagement Action ─────────────────────────────────────────────────────────

class ActionType(str, Enum):
    """
    All engagement actions a client can report.

    Positive signals raise a content type's session taste score;
    negative signals (skip, dismiss) lower it.
    """
    DWELL = "dwell"                         # passive 4-10 s view
    STRONG_DWELL = "strong_dwell"           # >10 s view (+30 % bonus in scoring)
    SKIP = "skip"                           # <1.5 s — negative signal
    LIKE = "like"
    SAVE = "save"
    SHARE = "share"
    COMMENT = "comment"
    CONNECTION_ACCEPT = "connection_accept"
    CONNECTION_DISMISS = "connection_dismiss"   # negative signal


# ── Action Signal Weights ─────────────────────────────────────────────────────

ACTION_WEIGHTS: dict[ActionType, int] = {
    ActionType.SAVE: 5,
    ActionType.SHARE: 4,
    ActionType.COMMENT: 4,
    ActionType.LIKE: 3,
    ActionType.CONNECTION_ACCEPT: 3,
    ActionType.DWELL: 2,
    ActionType.STRONG_DWELL: 2,     # +30 % bonus applied via avg_dwell threshold
    ActionType.SKIP: -1,
    ActionType.CONNECTION_DISMISS: -1,
}


# ── Feed Section Key ──────────────────────────────────────────────────────────

class NewsSectionKey(str, Enum):
    """
    Section identifiers returned by the news module's get_news_feed response.

    RIGHT_NOW maps to breaking-news priority pins.
    FOR_YOU_TODAY maps to the regular news pool.
    """
    RIGHT_NOW = "right_now"
    FOR_YOU_TODAY = "for_you_today"


# ── Mixer Configuration ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class ConsecutiveCap:
    """
    Maximum number of consecutive items of the same content type allowed
    in a single feed page before a forced break.
    """
    post: int = 3
    news: int = 2
    group: int = 1
    connection: int = 1

    def as_dict(self) -> dict[str, int]:
        return {
            "post": self.post,
            "news": self.news,
            "group": self.group,
            "connection": self.connection,
        }


@dataclass(frozen=True)
class MixerConfig:
    """
    Immutable configuration that governs the weighted-random feed mixer.

    page_size            : number of cards per feed page
    transition_threshold : when <= this many priority pins remain they are
                           interleaved (every 3rd slot) instead of prepended
    consecutive_caps     : per-type maximum consecutive run length
    """
    page_size: int = 20
    transition_threshold: int = 3
    consecutive_caps: ConsecutiveCap = ConsecutiveCap()


# ── Engagement Signal (domain, used by recommendation layer) ─────────────────

@dataclass(frozen=True)
class FeedEngagementSignal:
    """
    Immutable engagement signal passed from the application layer to the
    recommendation layer. The presentation layer converts Pydantic
    EngagementSignal → FeedEngagementSignal before calling update_session_taste.
    """
    item_id: str
    item_type: str        # "post" | "news" | "group" | "connection"
    action: str           # matches ActionType values
    dwell_ms: int | None = None


# ── Session Taste Configuration ───────────────────────────────────────────────

@dataclass(frozen=True)
class SessionTasteConfig:
    """
    Constants that govern Redis-backed session taste computation.

    ttl_seconds      : Redis TTL for the session taste key
    cold_start_items : signals seen below this count keep blend_factor = 0.0
                       (page defaults used exclusively)
    avg_dwell_bonus_threshold_ms : avg dwell above this value multiplies score by 1.3
    """
    ttl_seconds: int = 7200                    # 2 hours
    cold_start_items: int = 8
    avg_dwell_bonus_threshold_ms: int = 6000   # 6 seconds


# ── Page-Level Default Type-Mix Weights ───────────────────────────────────────

# Keyed by page number; pages beyond 5 use DEEP_PAGE_DEFAULTS.
PAGE_LEVEL_DEFAULTS: dict[int, dict[str, float]] = {
    1: {"post": 0.50, "news": 0.25, "group": 0.15, "connection": 0.10},
    2: {"post": 0.50, "news": 0.25, "group": 0.15, "connection": 0.10},
    3: {"post": 0.55, "news": 0.15, "group": 0.20, "connection": 0.10},
    4: {"post": 0.55, "news": 0.15, "group": 0.20, "connection": 0.10},
    5: {"post": 0.55, "news": 0.15, "group": 0.20, "connection": 0.10},
}

DEEP_PAGE_DEFAULTS: dict[str, float] = {
    "post": 0.65,
    "news": 0.05,
    "group": 0.15,
    "connection": 0.15,
}
