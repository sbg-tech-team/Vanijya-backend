"""
Home Feed Service — orchestrates the source recommenders + mixer.

This version delegates ALL item ranking to the owning modules' recommenders
(see pipelines.py) and only owns the type-mix. Taste/weights are intentionally
static for now (no session taste, Redis-session off) — a fixed ratio fed to the
weighted-random mixer with the existing max-consecutive caps.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID
from typing import Callable, Optional, TypeVar, cast

import redis
from sqlalchemy.orm import Session

from app.core.database.session import SessionLocal
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

_T = TypeVar("_T")


def _in_own_session(fn: Callable[[Session], _T]) -> _T:
    """Run `fn` with a fresh, dedicated DB session.

    The source pipelines run in parallel threads, and a SQLAlchemy Session is not
    thread-safe — each pipeline must own its session. Pool is 5+10, so 4 concurrent
    sessions are well within budget.
    """
    db = SessionLocal()
    try:
        return fn(db)
    finally:
        db.close()

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

    # Source pipelines run in PARALLEL — they are independent, and each owns its own
    # DB session (see _in_own_session). Wall-time ≈ slowest pipeline, not the sum.
    # The request-scoped `db` is intentionally not used here (it isn't thread-safe).
    tasks: dict[str, Callable[[], object]] = {
        # fetch_post_candidates self-manages its own (parallel) sessions, so it
        # doesn't need a dedicated one here — `db` is passed but unused by it.
        "post": lambda: fetch_post_candidates(db, profile_id, limit=POST_LIMIT),
        "news": lambda: _in_own_session(
            lambda s: fetch_news_feed(s, user_id)
        ),
        "connection": lambda: _in_own_session(
            lambda s: fetch_connection_candidates(s, r, user_id, page=page_num, limit=CONNECTION_LIMIT)
        ),
        "group": lambda: _in_own_session(
            lambda s: fetch_group_candidates(s, user_id, page=page_num, limit=GROUP_LIMIT)
        ),
    }

    results: dict[str, object] = {}
    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        futures = {key: pool.submit(fn) for key, fn in tasks.items()}
        for key, fut in futures.items():
            try:
                results[key] = fut.result()
            except Exception:
                results[key] = ([], []) if key == "news" else []

    post_candidates = results["post"]
    breaking_pins, news_candidates = cast(
        "tuple[list[FeedItem], list[FeedItem]]", results["news"]
    )
    conn_candidates = results["connection"]
    group_candidates = results["group"]

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
