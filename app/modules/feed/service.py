"""
Home Feed Service — orchestrates priority queue, pipelines, session taste, and mixer.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

# import redis  # re-enable when Redis / session taste is turned back on
from sqlalchemy.orm import Session

from app.modules.feed.schemas import (
    EngagementBatch,
    FeedCursor,
    FeedItem,
    FeedPageResponse,
)
# Session taste disabled for now — uncomment to re-enable
# from app.modules.feed.session_taste import (
#     compute_weights,
#     get_session_taste,
#     update_session_taste,
# )
from app.modules.feed.session_taste import PAGE_LEVEL_DEFAULTS, PAGE_LEVEL_DEEP
from app.modules.feed.pipelines import (
    fetch_connection_candidates,
    fetch_group_candidates,
    fetch_news_candidates,
    fetch_post_candidates,
    get_user_context,
)
from app.modules.feed.priority import resolve_priority_pins
from app.modules.feed.mixer import mix_feed

# Seen-item TTLs (seconds)
SEEN_TTL = {
    "post": 48 * 3600,
    "news": 48 * 3600,
    "group": 24 * 3600,
    "connection": 7 * 24 * 3600,
}


class ProfileNotFoundError(Exception):
    pass


# ── Seen-set helpers ──────────────────────────────────────────────────────────

def _seen_key(item_type: str, profile_id: int) -> str:
    key_map = {
        "post": f"seen:posts:{profile_id}",
        "news": f"seen:news:{profile_id}",
        "group": f"seen:groups:{profile_id}",
        "connection": f"seen:conn:{profile_id}",
        "breaking_news": f"seen:news:{profile_id}",
    }
    return key_map.get(item_type, f"seen:{item_type}:{profile_id}")


# def _get_seen_ids(rc, item_type: str, profile_id: int) -> set[str]:
#     key = _seen_key(item_type, profile_id) , this 
#     raw = rc.smembers(key)
#     return {s.decode() if isinstance(s, bytes) else s for s in raw}


# def mark_items_seen(rc, item_ids: list[str], item_type: str, profile_id: int) -> None:
#     if not item_ids:
#         return
#     key = _seen_key(item_type, profile_id)
#     rc.sadd(key, *item_ids)
#     rc.expire(key, SEEN_TTL.get(item_type, 48 * 3600))


# ── Advance cursors ───────────────────────────────────────────────────────────

def _advance_cursor(
    current: FeedCursor,
    items: list[FeedItem],
) -> FeedCursor:
    """Build next cursor from the last items of each type in the current page."""
    last_post = last_news = last_group = None
    conn_count = current.connection_cursor

    for item in reversed(items):
        if item.item_type == "post" and last_post is None:
            ts = item.data.get("created_at", datetime.now(timezone.utc).isoformat())
            last_post = f"{ts}|{item.item_id}"
        elif item.item_type == "news" and last_news is None:
            ts = item.data.get("published_at", datetime.now(timezone.utc).isoformat())
            last_news = f"{ts}|{item.item_id}"
        elif item.item_type == "group" and last_group is None:
            ts = item.data.get("created_at", datetime.now(timezone.utc).isoformat())
            last_group = f"{ts}|{item.item_id}"
        elif item.item_type == "connection":
            conn_count += 1

    return FeedCursor(
        post_cursor=last_post or current.post_cursor,
        news_cursor=last_news or current.news_cursor,
        group_cursor=last_group or current.group_cursor,
        connection_cursor=conn_count,
        page_num=current.page_num + 1,
    )


# ── Main feed builder ─────────────────────────────────────────────────────────

def get_home_feed(
    db: Session,
    user_id: UUID,
    cursor: Optional[FeedCursor] = None,
) -> FeedPageResponse:
    try:
        profile_id, commodity_names, role_name = get_user_context(db, user_id)
    except ValueError as e:
        raise ProfileNotFoundError(str(e))

    is_first_load = cursor is None
    if cursor is None:
        cursor = FeedCursor()

    page_num = cursor.page_num

    # Seen sets disabled (Redis off) — pass empty sets; re-enable with Redis:
    # seen_posts  = _get_seen_ids(rc, "post",       profile_id)
    # seen_news   = _get_seen_ids(rc, "news",       profile_id)
    # seen_groups = _get_seen_ids(rc, "group",      profile_id)
    # seen_conn   = _get_seen_ids(rc, "connection", profile_id)

    # Phase 1: priority pins (first load only)
    priority_pins: list[FeedItem] = []
    if is_first_load:
        priority_pins = resolve_priority_pins(
            db, profile_id, user_id, commodity_names, role_name
        )

    # Phase 2: run all source pipelines
    post_candidates = fetch_post_candidates(
        db, profile_id, user_id, set(), cursor.post_cursor
    )
    news_candidates = fetch_news_candidates(
        db, user_id, profile_id, commodity_names, role_name, set(), cursor.news_cursor
    )
    group_candidates = fetch_group_candidates(
        db, user_id, set(), cursor.group_cursor
    )
    conn_candidates = fetch_connection_candidates(
        db, user_id, profile_id, set(), cursor.connection_cursor
    )

    # Exclude priority pin IDs from regular pools to avoid duplication
    pin_ids = {p.item_id for p in priority_pins}
    post_candidates = [p for p in post_candidates if p.item_id not in pin_ids]
    news_candidates = [n for n in news_candidates if n.item_id not in pin_ids]

    candidates = {
        "post": post_candidates,
        "news": news_candidates,
        "group": group_candidates,
        "connection": conn_candidates,
    }

    # Session taste disabled — use static page-level defaults
    # taste = get_session_taste(rc, profile_id, session_id)
    # weights = compute_weights(taste, page_num)
    weights = dict(PAGE_LEVEL_DEFAULTS.get(page_num, PAGE_LEVEL_DEEP))

    # Mix feed
    mixed_items = mix_feed(candidates, weights, priority_pins)

    has_more = any(bool(v) for v in candidates.values())
    next_cursor = _advance_cursor(cursor, mixed_items)

    # Mark served items as seen (re-enable with Redis):
    # for item_type in ("post", "news", "group", "connection"):
    #     ids = [i.item_id for i in mixed_items if i.item_type == item_type]
    #     if ids:
    #         mark_items_seen(rc, ids, item_type, profile_id)
    # for item_type in ("post", "news"):
    #     ids = [p.item_id for p in priority_pins if p.item_type == item_type]
    #     if ids:
    #         mark_items_seen(rc, ids, item_type, profile_id)

    return FeedPageResponse(
        items=mixed_items,
        cursor=next_cursor,
        has_more=has_more,
        weights_used=weights,
    )


# ── Engagement submission ─────────────────────────────────────────────────────

def submit_engagement(
    user_id: UUID,
    batch: EngagementBatch,
) -> dict:
    # Session taste update disabled — uncomment to re-enable:
    # update_session_taste(rc, profile_id, batch.cursor.session_id, batch.signals)

    # Seen-set update disabled — uncomment to re-enable:
    # for sig in batch.signals:
    #     mark_items_seen(rc, [sig.item_id], sig.item_type, profile_id)

    return {"acknowledged": True, "signals_processed": len(batch.signals)}
