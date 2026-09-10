"""
Get Home Feed use case — orchestrates the source recommenders + mixer.

Delegates ALL item ranking to the owning modules' recommenders (see pipelines.py)
and only owns the type-mix. Taste/weights are intentionally static for now
(no session taste, Redis-session off) — a fixed ratio fed to the weighted-random
mixer with the existing max-consecutive caps.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, TypeVar, cast

from uuid import UUID
from typing import Optional

import redis
from sqlalchemy.orm import Session

from app.modules.home_feed.application.schemas import (
    FeedCursor,
    FeedItem,
    FeedPageResponse,
)
from app.modules.home_feed.mixer.pipelines import (
    fetch_connection_candidates,
    fetch_group_candidates,
    fetch_news_feed,
    fetch_post_candidates,
)
from app.core.database.session import SessionLocal
from app.modules.home_feed.mixer.mixer import mix_feed

_T = TypeVar("_T")


def _in_own_session(fn: Callable[[Session], _T]) -> _T:
    """Run `fn` with a fresh, dedicated DB session.

    The source pipelines run in parallel threads and a SQLAlchemy Session is not
    thread-safe, so each pipeline must own its session. Ported from
    app_old/modules/feed/service.py.
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
    # Run in parallel, as app_old did: sequentially this is the sum of four
    # round-trips instead of the slowest one. Each pipeline gets its OWN session
    # because a SQLAlchemy Session is not thread-safe and `db` belongs to the
    # request thread. A pipeline that raises degrades to empty rather than
    # failing the whole feed — app_old's behaviour.
    tasks = {
        "post": lambda: _in_own_session(
            lambda s: fetch_post_candidates(s, profile_id, limit=POST_LIMIT)
        ),
        "news": lambda: _in_own_session(
            lambda s: fetch_news_feed(s, user_id)
        ),
        "connection": lambda: _in_own_session(
            lambda s: fetch_connection_candidates(
                s, r, user_id, page=page_num, limit=CONNECTION_LIMIT
            )
        ),
        "group": lambda: _in_own_session(
            lambda s: fetch_group_candidates(
                s, user_id, page=page_num, limit=GROUP_LIMIT
            )
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

    post_candidates = cast("list[FeedItem]", results["post"])
    breaking_pins, news_candidates = cast(
        "tuple[list[FeedItem], list[FeedItem]]", results["news"]
    )
    conn_candidates = cast("list[FeedItem]", results["connection"])
    group_candidates = cast("list[FeedItem]", results["group"])

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
