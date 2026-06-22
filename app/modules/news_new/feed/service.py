import base64
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.news_new.feed.schemas import CursorMeta, FeedPage, NewsCard, NewsCardDetail
from app.modules.news_new.ingestion.models import RawArticle
from app.modules.news_new.intelligence.models import EnrichedArticle
from app.modules.news_new.news_user_interaction.models import (
    NewsArticleStats,
    NewsLike,
    NewsSave,
)

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 50

_ROLE_COL = {1: "role_trader", 2: "role_broker", 3: "role_exporter"}


def compute_time_on_platform(platform_arrived_at: datetime) -> str:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    delta = now - platform_arrived_at.replace(tzinfo=None)
    hours = int(delta.total_seconds() / 3600)
    if hours < 24:
        return f"{max(1, hours)}h"
    days = delta.days
    if days == 1:
        return "Yesterday"
    return f"{days} days ago"


def encode_cursor(article: RawArticle) -> str:
    raw = f"{article.platform_arrived_at.isoformat()}|{article.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, UUID] | None:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts_str, uid_str = raw.split("|", 1)
        return datetime.fromisoformat(ts_str), UUID(uid_str)
    except Exception:
        return None


def assemble_card(
    article: RawArticle,
    enriched: EnrichedArticle | None,
    stats: NewsArticleStats | None,
    is_liked: bool,
    is_saved: bool,
    role_score: float | None = None,
    final_score: float | None = None,
) -> NewsCard:
    return NewsCard(
        article_id=article.id,
        title=article.title,
        image_url=article.image_url,
        source_name=article.source_name,
        time_on_platform=compute_time_on_platform(article.platform_arrived_at),
        platform_arrived_at=article.platform_arrived_at,
        summary_bullets=enriched.summary_bullets if enriched else None,
        primary_factor=enriched.primary_factor if enriched else None,
        geo_category=enriched.geo_category if enriched else None,
        impact_direction=enriched.impact_direction if enriched else None,
        impact_score=enriched.impact_score if enriched else None,
        like_count=stats.like_count if stats else 0,
        share_count=stats.share_count if stats else 0,
        is_liked=is_liked,
        is_saved=is_saved,
        role_score=role_score,
        final_score=final_score,
    )


def assemble_card_detail(
    article: RawArticle,
    enriched: EnrichedArticle | None,
    stats: NewsArticleStats | None,
    is_liked: bool,
    is_saved: bool,
    role_score: float | None = None,
) -> NewsCardDetail:
    return NewsCardDetail(
        article_id=article.id,
        title=article.title,
        image_url=article.image_url,
        source_name=article.source_name,
        time_on_platform=compute_time_on_platform(article.platform_arrived_at),
        platform_arrived_at=article.platform_arrived_at,
        summary_bullets=enriched.summary_bullets if enriched else None,
        primary_factor=enriched.primary_factor if enriched else None,
        geo_category=enriched.geo_category if enriched else None,
        impact_direction=enriched.impact_direction if enriched else None,
        impact_score=enriched.impact_score if enriched else None,
        impact_explanation=enriched.impact_explanation if enriched else None,
        impact_factor=enriched.impact_factor if enriched else None,
        factor_scores=enriched.factor_scores if enriched else None,
        like_count=stats.like_count if stats else 0,
        share_count=stats.share_count if stats else 0,
        is_liked=is_liked,
        is_saved=is_saved,
        role_score=role_score,
        final_score=role_score,
        description=article.description,
        article_url=article.article_url,
        source_url=article.source_url,
        published_at=article.published_at,
        view_count=stats.view_count if stats else None,
        save_count=stats.save_count if stats else None,
    )


def get_trending_feed(
    db: Session,
    profile_id: int,
    role_id: int | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> FeedPage:
    """Reverse-chronological feed of enriched articles, ordered by platform_arrived_at."""
    limit = min(limit, MAX_PAGE_SIZE)

    q = (
        select(RawArticle)
        .where(
            RawArticle.is_active == True,
            RawArticle.intelligence_status == "enriched",
        )
        .order_by(RawArticle.platform_arrived_at.desc(), RawArticle.id.desc())
        .limit(limit + 1)
    )

    if cursor:
        parsed = decode_cursor(cursor)
        if parsed:
            ts, uid = parsed
            q = q.where(
                (RawArticle.platform_arrived_at < ts)
                | (
                    (RawArticle.platform_arrived_at == ts)
                    & (RawArticle.id < uid)
                )
            )

    articles = list(db.execute(q).scalars())
    has_more = len(articles) > limit
    if has_more:
        articles = articles[:limit]

    if not articles:
        return FeedPage(items=[], cursor=CursorMeta(next_cursor=None, has_more=False))

    return _build_feed_page(db, articles, profile_id, role_id, has_more)


def get_saved_feed(
    db: Session,
    profile_id: int,
    role_id: int | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> FeedPage:
    """Articles the user has saved, most-recently-saved first."""
    limit = min(limit, MAX_PAGE_SIZE)

    saved_q = (
        select(NewsSave.article_id)
        .where(NewsSave.profile_id == profile_id)
        .order_by(NewsSave.created_at.desc())
    )
    saved_ids = [row[0] for row in db.execute(saved_q).all()]

    if not saved_ids:
        return FeedPage(items=[], cursor=CursorMeta(next_cursor=None, has_more=False))

    articles_map = {
        a.id: a for a in db.execute(
            select(RawArticle).where(RawArticle.id.in_(saved_ids))
        ).scalars()
    }
    # Preserve save order
    articles = [articles_map[sid] for sid in saved_ids if sid in articles_map]

    if cursor:
        parsed = decode_cursor(cursor)
        if parsed:
            ts, uid = parsed
            articles = [
                a for a in articles
                if a.platform_arrived_at < ts or (a.platform_arrived_at == ts and a.id < uid)
            ]

    has_more = len(articles) > limit
    articles = articles[:limit]

    return _build_feed_page(db, articles, profile_id, role_id, has_more)


def get_filtered_feed(
    db: Session,
    profile_id: int,
    feed_filter: str,
    role_id: int | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> FeedPage:
    """Filter by geo_category (global | domestic | regional) via EnrichedArticle."""
    limit = min(limit, MAX_PAGE_SIZE)

    enriched_ids_q = (
        select(EnrichedArticle.raw_article_id)
        .where(EnrichedArticle.geo_category == feed_filter)
    )
    filtered_ids = [row[0] for row in db.execute(enriched_ids_q).all()]

    if not filtered_ids:
        return FeedPage(items=[], cursor=CursorMeta(next_cursor=None, has_more=False))

    q = (
        select(RawArticle)
        .where(
            RawArticle.is_active == True,
            RawArticle.id.in_(filtered_ids),
        )
        .order_by(RawArticle.platform_arrived_at.desc(), RawArticle.id.desc())
        .limit(limit + 1)
    )

    if cursor:
        parsed = decode_cursor(cursor)
        if parsed:
            ts, uid = parsed
            q = q.where(
                (RawArticle.platform_arrived_at < ts)
                | (
                    (RawArticle.platform_arrived_at == ts)
                    & (RawArticle.id < uid)
                )
            )

    articles = list(db.execute(q).scalars())
    has_more = len(articles) > limit
    if has_more:
        articles = articles[:limit]

    return _build_feed_page(db, articles, profile_id, role_id, has_more)


def get_article_detail(
    db: Session,
    article_id: UUID,
    profile_id: int,
    role_id: int | None = None,
) -> NewsCardDetail | None:
    article = db.execute(
        select(RawArticle).where(RawArticle.id == article_id)
    ).scalar_one_or_none()
    if article is None:
        return None

    enriched = db.execute(
        select(EnrichedArticle).where(EnrichedArticle.raw_article_id == article_id)
    ).scalar_one_or_none()

    stats = db.execute(
        select(NewsArticleStats).where(NewsArticleStats.article_id == article_id)
    ).scalar_one_or_none()

    is_liked = db.execute(
        select(NewsLike.id).where(
            NewsLike.profile_id == profile_id,
            NewsLike.article_id == article_id,
        )
    ).scalar_one_or_none() is not None

    is_saved = db.execute(
        select(NewsSave.id).where(
            NewsSave.profile_id == profile_id,
            NewsSave.article_id == article_id,
        )
    ).scalar_one_or_none() is not None

    role_score: float | None = None
    if enriched and role_id:
        col = _ROLE_COL.get(role_id)
        if col:
            role_score = float(getattr(enriched, col, 0.0))

    return assemble_card_detail(article, enriched, stats, is_liked, is_saved, role_score)


# ── Internal helper ───────────────────────────────────────────────────────────


def _build_feed_page(
    db: Session,
    articles: list[RawArticle],
    profile_id: int,
    role_id: int | None,
    has_more: bool,
) -> FeedPage:
    article_ids = [a.id for a in articles]

    enriched_map = {
        e.raw_article_id: e
        for e in db.execute(
            select(EnrichedArticle).where(EnrichedArticle.raw_article_id.in_(article_ids))
        ).scalars()
    }
    stats_map = {
        s.article_id: s
        for s in db.execute(
            select(NewsArticleStats).where(NewsArticleStats.article_id.in_(article_ids))
        ).scalars()
    }
    liked_ids = {
        row[0]
        for row in db.execute(
            select(NewsLike.article_id).where(
                NewsLike.profile_id == profile_id,
                NewsLike.article_id.in_(article_ids),
            )
        ).all()
    }
    saved_ids = {
        row[0]
        for row in db.execute(
            select(NewsSave.article_id).where(
                NewsSave.profile_id == profile_id,
                NewsSave.article_id.in_(article_ids),
            )
        ).all()
    }

    items = []
    for article in articles:
        enriched = enriched_map.get(article.id)
        role_score: float | None = None
        if enriched and role_id:
            col = _ROLE_COL.get(role_id)
            if col:
                role_score = float(getattr(enriched, col, 0.0))

        items.append(assemble_card(
            article,
            enriched,
            stats_map.get(article.id),
            is_liked=article.id in liked_ids,
            is_saved=article.id in saved_ids,
            role_score=role_score,
            final_score=role_score,
        ))

    next_cursor = encode_cursor(articles[-1]) if has_more else None
    return FeedPage(items=items, cursor=CursorMeta(next_cursor=next_cursor, has_more=has_more))
