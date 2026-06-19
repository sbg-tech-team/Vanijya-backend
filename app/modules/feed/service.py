"""
Home Feed Service — orchestrates the source recommenders + mixer.

This version delegates ALL item ranking to the owning modules' recommenders
(see pipelines.py) and only owns the type-mix. Taste/weights are intentionally
static for now (no session taste, Redis-session off) — a fixed ratio fed to the
weighted-random mixer with the existing max-consecutive caps.
"""
from __future__ import annotations

from uuid import UUID
from typing import Optional

import redis
from sqlalchemy.orm import Session

from app.modules.feed.schemas import (
    EngagementBatch,
    FeedCursor,
    FeedItem,
    FeedPageResponse,
)
from app.modules.feed.pipelines import (
    fetch_connection_candidates,
    fetch_group_candidates,
    fetch_news_feed,
    fetch_post_candidates,
)
from app.modules.feed.mixer import mix_feed

# Static type-mix ratio (no taste yet). Mixer normalises + applies consecutive caps.
FEED_WEIGHTS: dict[str, float] = {
    "post": 0.45,
    "news": 0.25,
    "group": 0.15,
    "connection": 0.15,
}

# Per-source fetch sizes
POST_LIMIT = 20
CONNECTION_LIMIT = 5
GROUP_LIMIT = 5


class ProfileNotFoundError(Exception):
    pass


# ── Main feed builder ─────────────────────────────────────────────────────────

def get_home_feed(
    db: Session,
    user_id: UUID,
    profile_id: int,
    r: redis.Redis,
    cursor: Optional[FeedCursor] = None,
) -> FeedPageResponse:
    is_first_load = cursor is None
    if cursor is None:
        cursor = FeedCursor()
    page_num = cursor.page_num

    # Source pipelines — each calls the owning module's recommender.
    post_candidates = fetch_post_candidates(db, profile_id, limit=POST_LIMIT)
    breaking_pins, news_candidates = fetch_news_feed(db, user_id)
    conn_candidates = fetch_connection_candidates(
        db, r, user_id, page=page_num, limit=CONNECTION_LIMIT
    )
    group_candidates = fetch_group_candidates(
        db, user_id, page=page_num, limit=GROUP_LIMIT
    )

    # Breaking news → priority pins, first load only. Avoid double-serving.
    priority_pins: list[FeedItem] = breaking_pins if is_first_load else []
    pin_ids = {p.item_id for p in priority_pins}
    news_candidates = [n for n in news_candidates if n.item_id not in pin_ids]

    candidates = {
        "post": post_candidates,
        "news": news_candidates,
        "group": group_candidates,
        "connection": conn_candidates,
    }

    weights = dict(FEED_WEIGHTS)
    mixed_items = mix_feed(candidates, weights, priority_pins)

    has_more = any(bool(v) for v in candidates.values())
    next_cursor = FeedCursor(page_num=page_num + 1)

    return FeedPageResponse(
        items=mixed_items,
        cursor=next_cursor,
        has_more=has_more,
        weights_used=weights,
    )


# ── Engagement submission (acknowledge-only for now) ───────────────────────────

def submit_engagement(
    user_id: UUID,
    batch: EngagementBatch,
) -> dict:
    # Signals are not yet forwarded to source modules — taste/forwarding is a
    # later step. The endpoint acknowledges receipt so the client can batch.
    return {"acknowledged": True, "signals_processed": len(batch.signals)}
