"""
Candidate Source Pipelines — run in parallel, each returns a list of FeedItem.

Post pipeline      : ~60 ranked posts
News pipeline      : ~15 news articles
Group Activity     : ~10 posts from user's groups (velocity-ranked)
Connection pipeline: top-3 unseen connection suggestions
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.feed.schemas import FeedItem
from app.modules.post.models import Post, PostLike, PostSave
from app.modules.news.models import NewsArticle, NewsEngagement
from app.modules.profile.models import Profile, Profile_Commodity, Commodity, Role
from app.modules.connections.models import UserConnection


# ── Seen-set helpers ──────────────────────────────────────────────────────────

def _parse_cursor_ts(cursor: Optional[str]) -> Optional[datetime]:
    if not cursor:
        return None
    try:
        ts_part = cursor.split("|")[0]
        return datetime.fromisoformat(ts_part)
    except Exception:
        return None


def _parse_cursor_id(cursor: Optional[str]) -> Optional[str]:
    if not cursor:
        return None
    parts = cursor.split("|")
    return parts[1] if len(parts) > 1 else None


def _make_cursor(dt: datetime, item_id: str) -> str:
    return f"{dt.isoformat()}|{item_id}"


# ── User context ──────────────────────────────────────────────────────────────

def get_user_context(db: Session, user_id: UUID) -> tuple[int, list[str], str]:
    """Returns (profile_id, commodity_names, role_name) looked up from user UUID."""
    profile = db.query(Profile).filter(Profile.users_id == user_id).first()
    if not profile:
        raise ValueError(f"Profile not found for user {user_id}")

    role_map = {1: "trader", 2: "broker", 3: "exporter"}
    role_name = role_map.get(profile.role_id, "trader")

    commodity_rows = (
        db.query(Commodity.name)
        .join(Profile_Commodity, Commodity.id == Profile_Commodity.commodity_id)
        .filter(Profile_Commodity.profile_id == profile.id)
        .all()
    )
    commodities = [r[0].lower() for r in commodity_rows]

    return profile.id, commodities, role_name


# ── Post Pipeline ─────────────────────────────────────────────────────────────

def fetch_post_candidates(
    db: Session,
    profile_id: int,
    user_id: UUID,
    seen_ids: set[str],
    post_cursor: Optional[str] = None,
    limit: int = 60,
) -> list[FeedItem]:
    cursor_ts = _parse_cursor_ts(post_cursor)

    query = (
        db.query(Post)
        .filter(Post.is_public == True)
        .filter(Post.profile_id != profile_id)
    )
    if cursor_ts:
        query = query.filter(Post.created_at < cursor_ts)

    posts = query.order_by(Post.created_at.desc()).limit(limit * 2).all()

    items: list[FeedItem] = []
    for p in posts:
        pid = str(p.id)
        if pid in seen_ids or len(items) >= limit:
            break
        is_liked = db.query(PostLike).filter_by(post_id=p.id, profile_id=profile_id).first() is not None
        is_saved = db.query(PostSave).filter_by(post_id=p.id, profile_id=profile_id).first() is not None
        items.append(FeedItem(
            item_type="post",
            item_id=pid,
            content_type_label="post",
            data={
                "id": p.id,
                "profile_id": p.profile_id,
                "category_id": p.category_id,
                "commodity_id": p.commodity_id,
                "caption": p.caption,
                "image_urls": p.image_urls,
                "like_count": p.like_count,
                "comment_count": p.comment_count,
                "save_count": p.save_count,
                "share_count": p.share_count,
                "view_count": p.view_count,
                "is_liked": is_liked,
                "is_saved": is_saved,
                "created_at": p.created_at.isoformat(),
                "allow_comments": p.allow_comments,
            },
        ))

    return items


# ── News Pipeline ─────────────────────────────────────────────────────────────

def fetch_news_candidates(
    db: Session,
    user_id: UUID,
    profile_id: int,
    commodity_names: list[str],
    role_name: str,
    seen_ids: set[str],
    news_cursor: Optional[str] = None,
    limit: int = 15,
) -> list[FeedItem]:
    cursor_ts = _parse_cursor_ts(news_cursor)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    query = (
        db.query(NewsArticle)
        .filter(NewsArticle.is_archived == False)
        .filter(NewsArticle.published_at > cutoff)
    )
    if cursor_ts:
        query = query.filter(NewsArticle.published_at < cursor_ts)

    articles = query.order_by(NewsArticle.published_at.desc()).limit(limit * 3).all()

    # commodity filter
    upper_commodities = [c.upper() for c in commodity_names]

    items: list[FeedItem] = []
    for a in articles:
        aid = str(a.id)
        if aid in seen_ids or len(items) >= limit:
            break

        # Include if article commodities overlap or article has no commodity tagging
        if a.commodities:
            article_upper = [c.upper() for c in a.commodities]
            if upper_commodities and not any(c in article_upper for c in upper_commodities):
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
            content_type_label="news",
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
            },
        ))

    return items


# ── Group Activity Pipeline ───────────────────────────────────────────────────

def fetch_group_candidates(
    db: Session,
    user_id: UUID,
    seen_ids: set[str],
    group_cursor: Optional[str] = None,
    limit: int = 10,
) -> list[FeedItem]:
    """
    Posts authored by members of groups the user belongs to, ranked by velocity.
    Falls back to [] if group_members/posts schema is unavailable.
    """
    try:
        cursor_ts = _parse_cursor_ts(group_cursor)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

        sql = text("""
            SELECT
                p.id,
                p.profile_id,
                p.caption,
                p.image_urls,
                p.like_count,
                p.comment_count,
                p.save_count,
                p.share_count,
                p.view_count,
                p.category_id,
                p.commodity_id,
                p.created_at,
                g.id   AS group_id,
                g.name AS group_name,
                (p.save_count * 3 + p.comment_count * 2 + p.like_count) /
                    POWER(EXTRACT(EPOCH FROM NOW() - p.created_at) / 3600.0 + 1, 1.5)
                    AS velocity_score
            FROM posts p
            JOIN profile pr ON pr.id = p.profile_id
            JOIN group_members gm_author ON gm_author.user_id = pr.users_id
            JOIN group_members gm_me     ON gm_me.group_id = gm_author.group_id
                                        AND gm_me.user_id = :user_id
            JOIN groups g ON g.id = gm_author.group_id
            WHERE p.created_at > :cutoff
              AND p.is_public = TRUE
              AND pr.users_id != :user_id
              :cursor_clause
            ORDER BY velocity_score DESC
            LIMIT :limit
        """)

        cursor_clause = ""
        params: dict = {
            "user_id": str(user_id),
            "cutoff": cutoff,
            "limit": limit * 2,
        }
        if cursor_ts:
            cursor_clause = "AND p.created_at < :cursor_ts"
            params["cursor_ts"] = cursor_ts

        # Rebuild with cursor clause interpolated (safe — no user input in cursor_clause)
        sql = text("""
            SELECT
                p.id,
                p.profile_id,
                p.caption,
                p.image_urls,
                p.like_count,
                p.comment_count,
                p.save_count,
                p.share_count,
                p.view_count,
                p.category_id,
                p.commodity_id,
                p.created_at,
                g.id   AS group_id,
                g.name AS group_name,
                (p.save_count * 3 + p.comment_count * 2 + p.like_count) /
                    POWER(EXTRACT(EPOCH FROM NOW() - p.created_at) / 3600.0 + 1, 1.5)
                    AS velocity_score
            FROM posts p
            JOIN profile pr ON pr.id = p.profile_id
            JOIN group_members gm_author ON gm_author.user_id = pr.users_id
            JOIN group_members gm_me     ON gm_me.group_id = gm_author.group_id
                                        AND gm_me.user_id = :user_id
            JOIN groups g ON g.id = gm_author.group_id
            WHERE p.created_at > :cutoff
              AND p.is_public = TRUE
              AND pr.users_id != :user_id
            ORDER BY velocity_score DESC
            LIMIT :limit
        """)
        if cursor_ts:
            sql = text("""
                SELECT
                    p.id,
                    p.profile_id,
                    p.caption,
                    p.image_urls,
                    p.like_count,
                    p.comment_count,
                    p.save_count,
                    p.share_count,
                    p.view_count,
                    p.category_id,
                    p.commodity_id,
                    p.created_at,
                    g.id   AS group_id,
                    g.name AS group_name,
                    (p.save_count * 3 + p.comment_count * 2 + p.like_count) /
                        POWER(EXTRACT(EPOCH FROM NOW() - p.created_at) / 3600.0 + 1, 1.5)
                        AS velocity_score
                FROM posts p
                JOIN profile pr ON pr.id = p.profile_id
                JOIN group_members gm_author ON gm_author.user_id = pr.users_id
                JOIN group_members gm_me     ON gm_me.group_id = gm_author.group_id
                                            AND gm_me.user_id = :user_id
                JOIN groups g ON g.id = gm_author.group_id
                WHERE p.created_at > :cutoff
                  AND p.is_public = TRUE
                  AND pr.users_id != :user_id
                  AND p.created_at < :cursor_ts
                ORDER BY velocity_score DESC
                LIMIT :limit
            """)

        rows = db.execute(sql, params).mappings().all()

        items: list[FeedItem] = []
        for r in rows:
            pid = str(r["id"])
            if pid in seen_ids or len(items) >= limit:
                break
            items.append(FeedItem(
                item_type="group",
                item_id=pid,
                content_type_label="group_activity",
                data={
                    "id": r["id"],
                    "profile_id": r["profile_id"],
                    "caption": r["caption"],
                    "image_urls": r["image_urls"],
                    "like_count": r["like_count"],
                    "comment_count": r["comment_count"],
                    "save_count": r["save_count"],
                    "share_count": r["share_count"],
                    "view_count": r["view_count"],
                    "category_id": r["category_id"],
                    "commodity_id": r["commodity_id"],
                    "created_at": r["created_at"].isoformat(),
                    "group_id": str(r["group_id"]),
                    "group_name": r["group_name"],
                    "velocity_score": float(r["velocity_score"] or 0),
                },
            ))
        return items

    except Exception:
        return []


# ── Connection Suggestions Pipeline ──────────────────────────────────────────

def fetch_connection_candidates(
    db: Session,
    user_id: UUID,
    profile_id: int,
    seen_ids: set[str],
    connection_cursor: int = 0,
    limit: int = 3,
) -> list[FeedItem]:
    """Return users not yet connected to, ranked by profile completeness proxy."""
    try:
        already_connected_ids = {
            str(r.following_id)
            for r in db.query(UserConnection.following_id)
            .filter(UserConnection.follower_id == user_id)
            .all()
        }
        already_connected_ids.add(str(user_id))  # exclude self

        candidates = (
            db.query(Profile)
            .filter(Profile.users_id.notin_([uuid.UUID(i) for i in already_connected_ids]))
            .offset(connection_cursor)
            .limit(limit * 5)
            .all()
        )

        items: list[FeedItem] = []
        for p in candidates:
            cid = str(p.users_id)
            if cid in seen_ids or len(items) >= limit:
                break
            items.append(FeedItem(
                item_type="connection",
                item_id=cid,
                content_type_label="connection",
                data={
                    "user_id": cid,
                    "profile_id": p.id,
                    "name": p.name,
                    "business_name": p.business_name,
                    "role_id": p.role_id,
                    "latitude": p.latitude,
                    "longitude": p.longitude,
                },
            ))
        return items

    except Exception:
        return []
