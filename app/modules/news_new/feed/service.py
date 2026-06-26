from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.news_new.feed.schemas import NewsFeedPage, NewsCard, NewsCardDetail
from app.modules.news_new.ingestion.models import RawArticle
from app.modules.news_new.intelligence.models import EnrichedArticle
from app.modules.news_new.news_user_interaction.models import (
    NewsArticleStats,
    NewsLike,
    NewsSave,
    NewsTrending,
)
from app.modules.news_new.news_recommendation_engine.profile_scorer import (
    apply_profile_boost,
    compute_profile_boost,
)
from app.modules.profile.models import Business, Commodity, Profile, Profile_Commodity

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 50

_ROLE_COL = {1: "role_trader", 2: "role_broker", 3: "role_exporter"}

_BUCKET_HOURS = [12, 24, 48]
_MIN_POOL_SIZE = 30
_RECOMMENDATION_CAP = 500


def _get_profile_context(db: Session, profile_id: int) -> tuple[int | None, list[str], str | None]:
    """Fetches (role_id, commodity_names, state) for the recommended feed."""
    profile = db.execute(
        select(Profile).where(Profile.id == profile_id)
    ).scalar_one_or_none()
    role_id = profile.role_id if profile else None

    commodity_names: list[str] = list(
        db.execute(
            select(Commodity.name)
            .join(Profile_Commodity, Profile_Commodity.commodity_id == Commodity.id)
            .where(Profile_Commodity.profile_id == profile_id)
        ).scalars()
    )
    state: str | None = db.execute(
        select(Business.state).where(Business.profile_id == profile_id)
    ).scalar_one_or_none()

    return role_id, commodity_names, state


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


def assemble_card(
    article: RawArticle,
    enriched: EnrichedArticle | None,
    stats: NewsArticleStats | None,
    is_liked: bool,
    is_saved: bool,
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
        is_government=enriched.is_government if enriched else False,
        impact_direction=enriched.impact_direction if enriched else None,
        impact_score=enriched.impact_score if enriched else None,
        like_count=stats.like_count if stats else 0,
        share_count=stats.share_count if stats else 0,
        is_liked=is_liked,
        is_saved=is_saved,
    )


def assemble_card_detail(
    article: RawArticle,
    enriched: EnrichedArticle | None,
    stats: NewsArticleStats | None,
    is_liked: bool,
    is_saved: bool,
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
        is_government=enriched.is_government if enriched else False,
        impact_direction=enriched.impact_direction if enriched else None,
        impact_score=enriched.impact_score if enriched else None,
        impact_explanation=enriched.impact_explanation if enriched else None,
        impact_factor=enriched.impact_factor if enriched else None,
        factor_scores=enriched.factor_scores if enriched else None,
        like_count=stats.like_count if stats else 0,
        share_count=stats.share_count if stats else 0,
        is_liked=is_liked,
        is_saved=is_saved,
        description=article.description,
        article_url=article.article_url,
        source_url=article.source_url,
        published_at=article.published_at,
        view_count=stats.view_count if stats else None,
        save_count=stats.save_count if stats else None,
    )


# ── Feed service functions ────────────────────────────────────────────────────

def get_recommended_feed(
    db: Session,
    profile_id: int,
    limit: int = DEFAULT_PAGE_SIZE,
    cursor_article_id: str | None = None,
) -> NewsFeedPage:
    """
    Landing-page recommended feed (GET /news/feed).

    Time-bucketed pool (<=12h → <=24h → <=48h) scored by Layer 1 + Layer 2 and
    returned sorted by final_score DESC. Scores stay server-side.

    Cursor is the article_id of the last returned article (same pattern as
    cursor_post_id in get_following_feed — find position, slice forward).
    """
    limit = min(limit, MAX_PAGE_SIZE)

    role_id, user_commodities, user_state = _get_profile_context(db, profile_id)

    candidates: list[RawArticle] = []
    for hours in _BUCKET_HOURS:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
        candidates = list(
            db.execute(
                select(RawArticle)
                .where(
                    RawArticle.is_active == True,
                    RawArticle.intelligence_status == "enriched",
                    RawArticle.platform_arrived_at >= cutoff,
                )
                .limit(_RECOMMENDATION_CAP)
            ).scalars()
        )
        if len(candidates) >= _MIN_POOL_SIZE:
            break

    if not candidates:
        return NewsFeedPage(articles=[], next_cursor=None)

    article_ids = [a.id for a in candidates]
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
    saved_ids_set = {
        row[0]
        for row in db.execute(
            select(NewsSave.article_id).where(
                NewsSave.profile_id == profile_id,
                NewsSave.article_id.in_(article_ids),
            )
        ).all()
    }

    scored: list[tuple[float, RawArticle, EnrichedArticle | None]] = []
    for article in candidates:
        enriched = enriched_map.get(article.id)
        role_score = 0.0
        if enriched and role_id:
            col = _ROLE_COL.get(role_id)
            if col:
                role_score = float(getattr(enriched, col, 0.0))
        profile_boost = compute_profile_boost(user_commodities, user_state, enriched)
        scored.append((apply_profile_boost(role_score, profile_boost), article, enriched))

    scored.sort(key=lambda x: x[0], reverse=True)

    start = 0
    if cursor_article_id:
        try:
            cid = UUID(cursor_article_id)
            ranked_ids = [art.id for _, art, _ in scored]
            try:
                start = ranked_ids.index(cid) + 1
            except ValueError:
                start = 0  # article aged out of window; restart
        except (ValueError, AttributeError):
            start = 0

    page = scored[start: start + limit]
    next_cursor = str(page[-1][1].id) if len(page) == limit else None

    articles = [
        assemble_card(
            article, enriched,
            stats_map.get(article.id),
            is_liked=article.id in liked_ids,
            is_saved=article.id in saved_ids_set,
        )
        for _, article, enriched in page
    ]
    return NewsFeedPage(articles=articles, next_cursor=next_cursor)


def get_trending_news(
    db: Session,
    profile_id: int,
    limit: int = DEFAULT_PAGE_SIZE,
    cursor_article_id: str | None = None,
) -> NewsFeedPage:
    """
    Trending + latest news (GET /news/trending).

    Merges two pools, velocity-first:
      1. Velocity pool (cap 100) — NewsTrending articles by velocity_score DESC
      2. Recency pool  (cap 50)  — latest enriched articles not in pool 1, by platform_arrived_at DESC
    No profile scoring or taste filtering.
    Cursor is the article_id of the last returned article.
    """
    _TRENDING_CAP = 100
    _RECENCY_CAP = 50

    limit = min(limit, MAX_PAGE_SIZE)

    velocity_articles: list[RawArticle] = list(
        db.execute(
            select(RawArticle)
            .join(NewsTrending, NewsTrending.article_id == RawArticle.id)
            .where(RawArticle.is_active == True, NewsTrending.velocity_score > 0)
            .order_by(NewsTrending.velocity_score.desc(), RawArticle.platform_arrived_at.desc())
            .limit(_TRENDING_CAP)
        ).scalars()
    )

    velocity_ids = {a.id for a in velocity_articles}

    recency_q = (
        select(RawArticle)
        .where(
            RawArticle.is_active == True,
            RawArticle.intelligence_status == "enriched",
        )
        .order_by(RawArticle.platform_arrived_at.desc())
        .limit(_RECENCY_CAP)
    )
    if velocity_ids:
        recency_q = recency_q.where(~RawArticle.id.in_(velocity_ids))

    recency_articles: list[RawArticle] = list(db.execute(recency_q).scalars())

    merged = velocity_articles + recency_articles

    if not merged:
        return NewsFeedPage(articles=[], next_cursor=None)

    start = 0
    if cursor_article_id:
        try:
            cid = UUID(cursor_article_id)
            all_ids = [a.id for a in merged]
            try:
                start = all_ids.index(cid) + 1
            except ValueError:
                start = 0
        except (ValueError, AttributeError):
            start = 0

    page = merged[start: start + limit]
    next_cursor = str(page[-1].id) if len(page) == limit else None

    result = _build_feed_page(db, page, profile_id)
    return NewsFeedPage(articles=result.articles, next_cursor=next_cursor)


def get_saved_feed(
    db: Session,
    profile_id: int,
    limit: int = DEFAULT_PAGE_SIZE,
    cursor_article_id: str | None = None,
) -> NewsFeedPage:
    """Articles the user has saved, most-recently-saved first."""
    limit = min(limit, MAX_PAGE_SIZE)

    saved_ids = [
        row[0]
        for row in db.execute(
            select(NewsSave.article_id)
            .where(NewsSave.profile_id == profile_id)
            .order_by(NewsSave.created_at.desc())
        ).all()
    ]

    if not saved_ids:
        return NewsFeedPage(articles=[], next_cursor=None)

    articles_map = {
        a.id: a
        for a in db.execute(
            select(RawArticle).where(RawArticle.id.in_(saved_ids))
        ).scalars()
    }
    all_articles = [articles_map[sid] for sid in saved_ids if sid in articles_map]

    start = 0
    if cursor_article_id:
        try:
            cid = UUID(cursor_article_id)
            all_ids = [a.id for a in all_articles]
            try:
                start = all_ids.index(cid) + 1
            except ValueError:
                start = 0
        except (ValueError, AttributeError):
            start = 0

    page = all_articles[start: start + limit]
    next_cursor = str(page[-1].id) if len(page) == limit else None

    result = _build_feed_page(db, page, profile_id)
    return NewsFeedPage(articles=result.articles, next_cursor=next_cursor)


def get_filtered_feed(
    db: Session,
    profile_id: int,
    feed_filter: str,
    limit: int = DEFAULT_PAGE_SIZE,
    cursor_article_id: str | None = None,
) -> NewsFeedPage:
    """
    Pure DB filter for global/domestic/government tabs — no recommendation, no scoring.
      - "global" / "domestic"  -> geo_category match
      - "government"           -> is_government = True (any geo)
    Ordered by platform_arrived_at DESC. Cursor is last article's id.
    """
    limit = min(limit, MAX_PAGE_SIZE)

    if feed_filter == "government":
        enriched_ids_q = (
            select(EnrichedArticle.raw_article_id)
            .where(EnrichedArticle.is_government == True)  # noqa: E712
        )
    else:
        enriched_ids_q = (
            select(EnrichedArticle.raw_article_id)
            .where(EnrichedArticle.geo_category == feed_filter)
        )
    filtered_ids = [row[0] for row in db.execute(enriched_ids_q).all()]

    if not filtered_ids:
        return NewsFeedPage(articles=[], next_cursor=None)

    q = (
        select(RawArticle)
        .where(
            RawArticle.is_active == True,
            RawArticle.id.in_(filtered_ids),
        )
        .order_by(RawArticle.platform_arrived_at.desc(), RawArticle.id.desc())
        .limit(limit + 1)
    )

    if cursor_article_id:
        try:
            cid = UUID(cursor_article_id)
            cursor_article = db.execute(
                select(RawArticle).where(RawArticle.id == cid)
            ).scalar_one_or_none()
            if cursor_article:
                ts = cursor_article.platform_arrived_at
                q = q.where(
                    (RawArticle.platform_arrived_at < ts)
                    | ((RawArticle.platform_arrived_at == ts) & (RawArticle.id < cid))
                )
        except (ValueError, AttributeError):
            pass

    articles = list(db.execute(q).scalars())
    has_next = len(articles) > limit
    if has_next:
        articles = articles[:limit]

    if not articles:
        return NewsFeedPage(articles=[], next_cursor=None)

    next_cursor = str(articles[-1].id) if has_next else None
    result = _build_feed_page(db, articles, profile_id)
    return NewsFeedPage(articles=result.articles, next_cursor=next_cursor)


def get_article_detail(
    db: Session,
    article_id: UUID,
    profile_id: int,
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

    return assemble_card_detail(article, enriched, stats, is_liked, is_saved)


# ── Internal helper ───────────────────────────────────────────────────────────

def _build_feed_page(
    db: Session,
    articles: list[RawArticle],
    profile_id: int,
) -> NewsFeedPage:
    """
    Batch-loads enriched/stats/liked/saved and builds NewsCards preserving input order.
    No scoring. Used by get_trending_news, get_filtered_feed, get_saved_feed.
    Callers set next_cursor themselves; this always returns next_cursor=None.
    """
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

    cards = [
        assemble_card(
            article,
            enriched_map.get(article.id),
            stats_map.get(article.id),
            is_liked=article.id in liked_ids,
            is_saved=article.id in saved_ids,
        )
        for article in articles
    ]
    return NewsFeedPage(articles=cards, next_cursor=None)
