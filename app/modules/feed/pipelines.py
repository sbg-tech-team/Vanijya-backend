"""
Candidate Source Pipelines — thin adapters over each module's own recommender.

No ranking / taste logic lives here anymore. Each pipeline simply CALLS the
owning module's recommendation function and maps the result into FeedItem.
The "which items" decision belongs to the source modules:

  post        -> post_recommendation_module.get_recommended_posts
  news        -> news_new.feed.service.get_trending_news
  connection  -> connections.get_recommendations  (sync; needs a Redis handle)
  group       -> groups.get_group_suggestions     (groups to join)

Every pipeline is defensive: if its source module raises, it returns [] so a
single failing module degrades gracefully instead of breaking the whole feed.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable
from uuid import UUID

import redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database.session import SessionLocal
from app.modules.feed.schemas import FeedItem
from app.modules.post.post_recommendation_module.service import (
    get_recommended_posts,
    get_popular_posts,
)
from app.modules.post.service import get_following_feed
from app.modules.connections.service import (
    get_recommendations as get_connection_recommendations,
)
from app.modules.groups.service import get_group_suggestions
from app.modules.profile.models import Profile
from app.modules.news_new.feed.service import (
    get_trending_news as _get_news_trending_feed,
    get_recommended_feed as _get_news_recommended_feed,
)


# ── Post pipeline ───────────────────────────────────────────────────────────────

# Blend ratio for the `post` type — recency of followed people dominates,
# popular posts a solid minority, personalised recommendation the smallest share.
POST_BLEND = {"following": 0.50, "popular": 0.30, "recommendation": 0.20}


def _in_own_session(fn: Callable[[Session], object]) -> object:
    """Run `fn` with a fresh, dedicated DB session (SQLAlchemy Session is not
    thread-safe, so each parallel sub-source must own its own)."""
    s = SessionLocal()
    try:
        return fn(s)
    finally:
        s.close()


def fetch_post_candidates(
    db: Session,
    profile_id: int,
    limit: int = 20,
) -> list[FeedItem]:
    """Blended post candidates from three of the post module's own recommenders:

      following      → get_following_feed   (recency of people you follow — most)
      popular        → get_popular_posts    (velocity-ranked popular posts)
      recommendation → get_recommended_posts (personalised ANN feed — least)

    The three sources run IN PARALLEL (each in its own session) — they are
    independent and the recommender is the slow one, so wall-time ≈ slowest
    source, not the sum. `db` is intentionally unused here (not thread-safe).

    Items are taken by ratio (POST_BLEND) of `limit`, deduped by post id with
    following winning ties, then back-filled from any leftover so the page still
    fills. All three already return FeedPostCard (is_liked/is_saved/is_following
    + author info), so no enrichment is needed. Each source is defensive — a
    failing one contributes [] rather than breaking the post type.
    """
    sub_tasks: dict[str, Callable[[], object]] = {
        "following": lambda: _in_own_session(
            lambda s: get_following_feed(s, profile_id, limit=limit).posts
        ),
        "popular": lambda: _in_own_session(
            lambda s: get_popular_posts(s, profile_id, limit=limit)
        ),
        "recommendation": lambda: _in_own_session(
            lambda s: get_recommended_posts(s, profile_id, limit=limit)
        ),
    }

    fetched: dict[str, list] = {}
    with ThreadPoolExecutor(max_workers=len(sub_tasks)) as pool:
        futures = {key: pool.submit(fn) for key, fn in sub_tasks.items()}
        for key, fut in futures.items():
            try:
                res = fut.result()
                fetched[key] = res if isinstance(res, list) else []
            except Exception:
                fetched[key] = []

    following = fetched["following"]
    popular = fetched["popular"]
    recommendation = fetched["recommendation"]

    quotas = {
        "following": round(limit * POST_BLEND["following"]),
        "popular": round(limit * POST_BLEND["popular"]),
    }
    quotas["recommendation"] = max(0, limit - quotas["following"] - quotas["popular"])

    sources = (
        ("following", following),
        ("popular", popular),
        ("recommendation", recommendation),
    )

    seen_ids: set = set()
    picked: list = []

    # Quota pass — take each source's share in priority order.
    for name, cards in sources:
        taken = 0
        for card in cards:
            if taken >= quotas[name]:
                break
            if card.id in seen_ids:
                continue
            seen_ids.add(card.id)
            picked.append(card)
            taken += 1

    # Back-fill pass — top up to `limit` from any leftover, same priority order.
    if len(picked) < limit:
        for _, cards in sources:
            for card in cards:
                if len(picked) >= limit:
                    break
                if card.id in seen_ids:
                    continue
                seen_ids.add(card.id)
                picked.append(card)

    return [
        FeedItem(
            item_type="post",
            item_id=str(card.id),
            content_type_label="post",
            data=card.model_dump(mode="json"),
        )
        for card in picked
    ]


# ── News pipeline ────────────────────────────────────────────────────────────────

NEWS_LIMIT = 20


def fetch_news_feed(
    db: Session,
    user_id: UUID,
    state: str = "",
    scope: str = "national",
) -> tuple[list[FeedItem], list[FeedItem]]:
    """News candidates from news_new for the home feed — trending then personalised.

    Looks up the caller's profile, then pulls TWO of the news module's own feeds:
      1. get_trending_news     — velocity + latest pools (recent-first)
      2. get_recommended_feed  — role/commodity/state personalised (recent-first)
    They are concatenated trending-block-first and deduped by article_id, so the
    trending block leads and the recommendation feed back-fills with anything new.

    Breaking news is omitted by design — returns (breaking_pins=[], news_pool).
    Each sub-feed is defensive: a failing one contributes [] rather than breaking
    the news type.
    """
    try:
        profile = db.execute(
            select(Profile).where(Profile.users_id == user_id)
        ).scalar_one_or_none()
        if profile is None:
            return [], []

        def _safe(fn) -> list:
            try:
                page = fn()
                return page.articles if page else []
            except Exception:
                return []

        trending = _safe(lambda: _get_news_trending_feed(db, profile_id=profile.id, limit=NEWS_LIMIT))
        recommended = _safe(lambda: _get_news_recommended_feed(db, profile_id=profile.id, limit=NEWS_LIMIT))

        seen_ids: set = set()
        news_items: list[FeedItem] = []
        for card in list(trending) + list(recommended):
            if card.article_id in seen_ids:
                continue
            seen_ids.add(card.article_id)
            news_items.append(
                FeedItem(
                    item_type="news",
                    item_id=str(card.article_id),
                    content_type_label="news",
                    data=card.model_dump(mode="json"),
                )
            )
        return [], news_items
    except Exception:
        return [], []


# ── Connection pipeline ──────────────────────────────────────────────────────────

def fetch_connection_candidates(
    db: Session,
    r: redis.Redis,
    user_id: UUID,
    page: int = 1,
    limit: int = 5,
) -> list[FeedItem]:
    """Ranked connection suggestions from the connections recommender.
    Seen-set + exclusions are handled inside that module (its own Redis)."""
    try:
        resp = get_connection_recommendations(db, r, user_id, page=page, limit=limit)
    except Exception:
        return []

    return [
        FeedItem(
            item_type="connection",
            item_id=str(res["user_id"]),
            content_type_label="connection",
            data=res,
        )
        for res in resp.get("results", [])
    ]


# ── Group pipeline ────────────────────────────────────────────────────────────────

def fetch_group_candidates(
    db: Session,
    user_id: UUID,
    page: int = 1,
    limit: int = 5,
) -> list[FeedItem]:
    """'Groups you might join' suggestions from the groups recommender."""
    try:
        resp = get_group_suggestions(db, user_id, page=page, limit=limit)
    except Exception:
        return []

    items: list[FeedItem] = []
    for sug in resp.get("results", []):
        group_out = sug.group
        data = group_out.model_dump(mode="json")
        data["match_score"] = sug.match_score
        data["match_reasons"] = sug.match_reasons
        items.append(
            FeedItem(
                item_type="group",
                item_id=str(group_out.id),
                content_type_label="group_suggestion",
                data=data,
            )
        )
    return items
