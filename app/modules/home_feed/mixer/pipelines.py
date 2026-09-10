"""
Candidate Source Pipelines — thin adapters over each module's own recommender.

No ranking / taste logic lives here anymore. Each pipeline simply CALLS the
owning module's recommendation function and maps the result into FeedItem.
The "which items" decision belongs to the source modules:

  post        -> post_recommendation_module.get_recommended_posts
  news        -> news.GetFeedUseCase (trending + default feed types)
  connection  -> connections.get_recommendations  (sync; needs a Redis handle)
  group       -> groups.get_group_suggestions     (groups to join)

Every pipeline is defensive: if its source module raises, it returns [] so a
single failing module degrades gracefully instead of breaking the whole feed.
"""
from __future__ import annotations

from uuid import UUID

import redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.home_feed.presentation.schemas import FeedItem
from app.modules.post.recommendation.engine import get_recommended_posts
from app.modules.news.application.use_cases.get_feed import GetFeedUseCase
from app.modules.news.data.repository import NewsRepository
from app.modules.news.presentation.schemas import NewsCardOut
from app.modules.news.recommendation.engine import NewsRecommendationEngine
from app.modules.profile.data.models import Profile
from app.modules.connections.application.use_cases.service import (
    get_recommendations as get_connection_recommendations,
)
from app.modules.groups.application.use_cases.service import get_group_suggestions

NEWS_LIMIT = 20


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
    """News candidates for the home feed — trending then personalised.

    Looks up the caller's profile, then pulls TWO of the news module's own
    feed types: 'trending' (velocity + recency pools) and 'default'
    (role/commodity/state personalised). Concatenated trending-block-first
    and deduped by article_id, so the trending block leads and the
    recommendation feed back-fills with anything new.

    Breaking news is omitted by design — returns (breaking_pins=[], news_pool),
    matching app_v1_backup/modules/feed/pipelines.py exactly.
    """
    try:
        profile = db.execute(
            select(Profile).where(Profile.users_id == user_id)
        ).scalar_one_or_none()
        if profile is None:
            return [], []

        repo = NewsRepository(db)
        engine = NewsRecommendationEngine(db)
        use_case = GetFeedUseCase(repo=repo, engine=engine)

        def _safe(feed_type: str) -> list:
            try:
                page = use_case.execute(
                    profile_id=profile.id,
                    role_id=profile.role_id,
                    commodity_interests=[],
                    home_state=None,
                    feed_type=feed_type,
                    page_size=NEWS_LIMIT,
                )
                return page.articles if page else []
            except Exception:
                return []

        trending = _safe("trending")
        recommended = _safe("default")

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
                    data=NewsCardOut.model_validate(card).model_dump(mode="json"),
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
