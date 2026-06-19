from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel


# ── Cursor ────────────────────────────────────────────────────────────────────

class FeedCursor(BaseModel):
    # Recommenders are page-based, so the feed cursor is just a page counter.
    # (Timestamp/offset cursors removed — pagination is delegated to each source.)
    page_num: int = 1


# ── Engagement signals (client → backend) ────────────────────────────────────

ItemType = Literal["post", "news", "group", "connection"]

ActionType = Literal[
    "dwell",          # passive dwell (4–10 s)
    "strong_dwell",   # >10 s
    "skip",           # <1.5 s
    "like",
    "save",
    "share",
    "comment",
    "connection_accept",
    "connection_dismiss",
]


class EngagementSignal(BaseModel):
    item_id: str
    item_type: ItemType
    action: ActionType
    dwell_ms: Optional[int] = None   # present for dwell / strong_dwell / skip


class EngagementBatch(BaseModel):
    signals: list[EngagementSignal]
    cursor: Optional[FeedCursor] = None


# ── Feed item (backend → client) ─────────────────────────────────────────────

class FeedItem(BaseModel):
    item_type: ItemType
    item_id: str
    data: dict[str, Any]
    is_priority: bool = False
    content_type_label: str = ""   # "post" | "news" | "group_activity" | "connection"


# ── Feed page response ────────────────────────────────────────────────────────

class FeedPageResponse(BaseModel):
    items: list[FeedItem]
    cursor: FeedCursor
    has_more: bool
    weights_used: Optional[dict[str, float]] = None   # debug info
