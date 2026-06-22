from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.news_new.intelligence.models import EnrichedArticle
from app.modules.news_new.news_recommendation_engine.models import (
    ArticleRecommendationScore,
    FeedRankingCache,
)

_CACHE_TTL_HOURS = 2

# Role id → EnrichedArticle column name.
_ROLE_COL = {1: "role_trader", 2: "role_broker", 3: "role_exporter"}


def compute_role_score(db: Session, article_id: UUID, role_id: int) -> float:
    """
    Mechanism 1 (role-based): read the pre-computed role relevance stored on
    EnrichedArticle. Returns 0.0 if the article hasn't been enriched yet.
    """
    enriched = db.execute(
        select(EnrichedArticle).where(EnrichedArticle.raw_article_id == article_id)
    ).scalar_one_or_none()
    if enriched is None:
        return 0.0
    col = _ROLE_COL.get(role_id, "role_trader")
    return float(getattr(enriched, col, 0.0))


def upsert_recommendation_score(
    db: Session,
    profile_id: int,
    article_id: UUID,
    role_score: float,
    profile_score: float | None = None,
    taste_score: float | None = None,
    model_version: str | None = None,
) -> ArticleRecommendationScore:
    """
    Write or update a recommendation score row.
    Phase 1: final_score == role_score.
    Phase 2+: replace with weighted sum once mechanisms 2 and 3 are wired in.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    final_score = role_score  # Phase 1 placeholder

    existing = db.execute(
        select(ArticleRecommendationScore).where(
            ArticleRecommendationScore.profile_id == profile_id,
            ArticleRecommendationScore.article_id == article_id,
        )
    ).scalar_one_or_none()

    if existing:
        existing.role_score = role_score
        existing.profile_score = profile_score
        existing.taste_score = taste_score
        existing.final_score = final_score
        existing.computed_at = now
        existing.model_version = model_version
        existing.is_served = False
        db.add(existing)
        return existing

    row = ArticleRecommendationScore(
        profile_id=profile_id,
        article_id=article_id,
        role_score=role_score,
        profile_score=profile_score,
        taste_score=taste_score,
        final_score=final_score,
        computed_at=now,
        model_version=model_version,
    )
    db.add(row)
    return row


def get_recommendation_scores(
    db: Session,
    profile_id: int,
    article_ids: list[UUID],
) -> list[ArticleRecommendationScore]:
    return list(
        db.execute(
            select(ArticleRecommendationScore).where(
                ArticleRecommendationScore.profile_id == profile_id,
                ArticleRecommendationScore.article_id.in_(article_ids),
            )
        ).scalars()
    )


def get_feed_ranking_cache(
    db: Session,
    profile_id: int,
    feed_type: str = "default",
) -> FeedRankingCache | None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return db.execute(
        select(FeedRankingCache).where(
            FeedRankingCache.profile_id == profile_id,
            FeedRankingCache.feed_type == feed_type,
            FeedRankingCache.expires_at > now,
        )
    ).scalar_one_or_none()


def upsert_feed_ranking_cache(
    db: Session,
    profile_id: int,
    ranked_article_ids: list[UUID],
    feed_type: str = "default",
) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    expires = now + timedelta(hours=_CACHE_TTL_HOURS)

    existing = db.execute(
        select(FeedRankingCache).where(
            FeedRankingCache.profile_id == profile_id,
            FeedRankingCache.feed_type == feed_type,
        )
    ).scalar_one_or_none()

    ids_as_str = [str(aid) for aid in ranked_article_ids]

    if existing:
        existing.ranked_article_ids = ids_as_str
        existing.computed_at = now
        existing.expires_at = expires
        db.add(existing)
    else:
        db.add(FeedRankingCache(
            profile_id=profile_id,
            feed_type=feed_type,
            ranked_article_ids=ids_as_str,
            computed_at=now,
            expires_at=expires,
        ))


def invalidate_feed_ranking_cache(
    db: Session,
    profile_id: int,
    feed_type: str = "default",
) -> None:
    cache = db.execute(
        select(FeedRankingCache).where(
            FeedRankingCache.profile_id == profile_id,
            FeedRankingCache.feed_type == feed_type,
        )
    ).scalar_one_or_none()
    if cache:
        db.delete(cache)
