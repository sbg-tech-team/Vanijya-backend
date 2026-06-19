"""
Candidate Source Pipelines — thin adapters over each module's own recommender.

No ranking / taste logic lives here anymore. Each pipeline simply CALLS the
owning module's recommendation function and maps the result into FeedItem.
The "which items" decision belongs to the source modules:

  post        -> post_recommendation_module.get_recommended_posts
  news        -> news.get_news_feed              (right_now + for_you_today sections)
  connection  -> connections.get_recommendations  (sync; needs a Redis handle)
  group       -> groups.get_group_suggestions     (groups to join)

Every pipeline is defensive: if its source module raises, it returns [] so a
single failing module degrades gracefully instead of breaking the whole feed.
"""
from __future__ import annotations

from uuid import UUID

import redis
from sqlalchemy.orm import Session

from app.modules.feed.schemas import FeedItem
from app.modules.post.post_recommendation_module.service import get_recommended_posts
from app.modules.news.service import get_news_feed
from app.modules.connections.service import (
    get_recommendations as get_connection_recommendations,
)
from app.modules.groups.service import get_group_suggestions


# ── Post pipeline ───────────────────────────────────────────────────────────────

def fetch_post_candidates(
    db: Session,
    profile_id: int,
    limit: int = 20,
) -> list[FeedItem]:
    """Personalised posts from the post recommender. Cards already carry
    is_liked / is_saved / is_following / author info — no enrichment needed."""
    try:
        cards = get_recommended_posts(db, profile_id, limit=limit)
    except Exception:
        return []

    return [
        FeedItem(
            item_type="post",
            item_id=str(card.id),
            content_type_label="post",
            data=card.model_dump(mode="json"),
        )
        for card in cards
    ]


# ── News pipeline ────────────────────────────────────────────────────────────────

def fetch_news_feed(
    db: Session,
    user_id: UUID,
    state: str = "",
    scope: str = "national",
) -> tuple[list[FeedItem], list[FeedItem]]:
    """
    Single get_news_feed call → (breaking_pins, news_pool).

      'right_now'     section → priority pins  (is_priority=True)
      'for_you_today' section → regular news pool
    """
    try:
        feed = get_news_feed(db, user_id, state=state, scope=scope)
    except Exception:
        return [], []

    sections = {s.key: s.articles for s in feed.sections}

    def _to_item(article, *, is_priority: bool) -> FeedItem:
        return FeedItem(
            item_type="news",
            item_id=str(article.id),
            is_priority=is_priority,
            content_type_label="breaking_news" if is_priority else "news",
            data=article.model_dump(mode="json"),
        )

    breaking = [_to_item(a, is_priority=True) for a in sections.get("right_now", [])]
    news_pool = [_to_item(a, is_priority=False) for a in sections.get("for_you_today", [])]
    return breaking, news_pool


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
