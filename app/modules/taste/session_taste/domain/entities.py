"""
Session taste domain entities — pure Python, no external dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ActionType(str, Enum):
    """
    All interaction signal types across every module that writes session taste.
    Post, News, Connections, Feed.
    """
    # ── Post & News ───────────────────────────────────────────────────────────
    IMPRESSION      = "impression"
    VIEW            = "view"
    DWELL_BOUNCE    = "dwell_bounce"
    DWELL_SHORT     = "dwell_short"
    DWELL_MEDIUM    = "dwell_medium"
    DWELL_LONG      = "dwell_long"
    OPEN_READ_MORE  = "open_read_more"
    OPEN_CAROUSEL   = "open_carousel"
    OPEN_COMMENTS   = "open_comments"
    LINK_CLICK      = "link_click"
    LIKE            = "like"
    SAVE            = "save"
    COMMENT         = "comment"
    SHARE           = "share"
    REVISIT         = "revisit"
    # ── Connections ───────────────────────────────────────────────────────────
    CONNECTION_VIEW    = "connection_view"
    CONNECTION_ACCEPT  = "connection_accept"
    CONNECTION_DISMISS = "connection_dismiss"
    # ── Feed ─────────────────────────────────────────────────────────────────
    FEED_SKIP  = "feed_skip"
    FEED_PAUSE = "feed_pause"


@dataclass(frozen=True)
class SessionSignal:
    """One interaction signal to ingest into a module's session taste hash."""
    dimension_type: str      # "category" | "commodity" | "author" | "role" …
    dimension_key: str       # e.g. "deal_req", "42", "123"
    action: ActionType
    occurred_at_unix: int    # unix timestamp


@dataclass(frozen=True)
class DimScore:
    """
    Decoded per-key score data read from one Redis hash field group.
    Returned by the repository; consumed by application-layer use cases.
    """
    key: str
    pos: float = 0.0
    neg: float = 0.0
    conf: float = 0.0
    cnt: int = 0
    last_ts: int = 0         # unix timestamp of last contributing event
