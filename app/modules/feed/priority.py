"""
Phase 1 — Priority Queue Resolver.

Surfaces two categories of time-critical content:
  1. Unseen posts from followed users (last 6 h, max 5)
  2. Breaking news (severity ≥ 8, last 3 h, user's commodities, max 2)

Total max priority items: 7
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

# import redis  # re-enable when Redis is turned back on
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.feed.schemas import FeedItem
from app.modules.news.models import NewsArticle
from app.modules.connections.models import UserConnection
from app.modules.post.models import Post, PostLike, PostSave
from app.modules.profile.models import Profile

FOLLOWED_USER_WINDOW_H = 6
BREAKING_NEWS_WINDOW_H = 3
BREAKING_SEVERITY_THRESHOLD = 8.0
MAX_FOLLOWED_PINS = 5
MAX_BREAKING_PINS = 2


def resolve_priority_pins(
    db: Session,
    profile_id: int,
    user_id: UUID,
    commodity_names: list[str],
    role_name: str,
) -> list[FeedItem]:
    pins: list[FeedItem] = []
    pins.extend(_unseen_followed_posts(db, profile_id, user_id))
    pins.extend(_breaking_news(db, profile_id, user_id, commodity_names, role_name))
    return pins


# ── Unseen posts from followed users ─────────────────────────────────────────

def _unseen_followed_posts(
    db: Session,
    profile_id: int,
    user_id: UUID,
) -> list[FeedItem]:
    # seen_ids from Redis disabled — using empty set for now
    # seen_key = f"seen:posts:{profile_id}"
    # seen_ids = {s.decode() if isinstance(s, bytes) else s for s in rc.smembers(seen_key)}
    seen_ids: set[str] = set()

    cutoff = datetime.now(timezone.utc) - timedelta(hours=FOLLOWED_USER_WINDOW_H)

    sql = text("""
        SELECT p.*
        FROM posts p
        JOIN profile pr ON pr.id = p.profile_id
        JOIN user_connections uc ON uc.following_id = pr.users_id
        WHERE uc.follower_id = :user_id
          AND p.created_at > :cutoff
          AND p.is_public = TRUE
        ORDER BY p.created_at DESC
        LIMIT :limit
    """)

    rows = db.execute(sql, {
        "user_id": str(user_id),
        "cutoff": cutoff,
        "limit": MAX_FOLLOWED_PINS * 3,
    }).mappings().all()

    items: list[FeedItem] = []
    for r in rows:
        pid = str(r["id"])
        if pid in seen_ids or len(items) >= MAX_FOLLOWED_PINS:
            break
        is_liked = db.query(PostLike).filter_by(post_id=r["id"], profile_id=profile_id).first() is not None
        is_saved = db.query(PostSave).filter_by(post_id=r["id"], profile_id=profile_id).first() is not None
        items.append(FeedItem(
            item_type="post",
            item_id=pid,
            is_priority=True,
            content_type_label="post",
            data={
                "id": r["id"],
                "profile_id": r["profile_id"],
                "caption": r["caption"],
                "image_urls": r["image_urls"],
                "category_id": r["category_id"],
                "commodity_id": r["commodity_id"],
                "like_count": r["like_count"],
                "comment_count": r["comment_count"],
                "save_count": r["save_count"],
                "share_count": r["share_count"],
                "view_count": r["view_count"],
                "is_liked": is_liked,
                "is_saved": is_saved,
                "created_at": r["created_at"].isoformat(),
                "allow_comments": r["allow_comments"],
            },
        ))
    return items


# ── Breaking news ─────────────────────────────────────────────────────────────

def _breaking_news(
    db: Session,
    profile_id: int,
    user_id: UUID,
    commodity_names: list[str],
    role_name: str,
) -> list[FeedItem]:
    # seen_ids from Redis disabled — using empty set for now
    # seen_key = f"seen:news:{profile_id}"
    # seen_ids = {s.decode() if isinstance(s, bytes) else s for s in rc.smembers(seen_key)}
    seen_ids: set[str] = set()

    cutoff = datetime.now(timezone.utc) - timedelta(hours=BREAKING_NEWS_WINDOW_H)
    upper_commodities = [c.upper() for c in commodity_names]

    articles = (
        db.query(NewsArticle)
        .filter(NewsArticle.severity >= BREAKING_SEVERITY_THRESHOLD)
        .filter(NewsArticle.published_at > cutoff)
        .filter(NewsArticle.is_archived == False)
        .order_by(NewsArticle.severity.desc(), NewsArticle.published_at.desc())
        .limit(MAX_BREAKING_PINS * 5)
        .all()
    )

    items: list[FeedItem] = []
    for a in articles:
        aid = str(a.id)
        if aid in seen_ids or len(items) >= MAX_BREAKING_PINS:
            break
        if a.commodities and upper_commodities:
            article_upper = [c.upper() for c in a.commodities]
            if not any(c in article_upper for c in upper_commodities):
                continue

        role_impact = None
        if role_name == "trader":
            role_impact = a.trader_impact
        elif role_name == "broker":
            role_impact = a.broker_impact
        elif role_name == "exporter":
            role_impact = a.exporter_impact

        items.append(FeedItem(
            item_type="news",
            item_id=aid,
            is_priority=True,
            content_type_label="breaking_news",
            data={
                "id": aid,
                "title": a.title,
                "summary": a.summary,
                "url": a.url,
                "image_url": a.image_url,
                "published_at": a.published_at.isoformat(),
                "severity": a.severity,
                "commodities": a.commodities or [],
                "regions": a.regions or [],
                "role_impact": role_impact,
                "cluster_id": a.cluster_id,
                "is_breaking": True,
            },
        ))
    return items
