"""
Concrete implementation of INewsRepository using SQLAlchemy.

Called by application use cases via the INewsRepository interface.
Never imported directly by application/ or presentation/ — always via DI.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select, update, delete, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.modules.news.domain.entities import (
    EnrichedArticle as DomainEnrichedArticle,
    FeedRankingCache as DomainFeedRankingCache,
    NewsArticleStats as DomainNewsArticleStats,
    NewsInteractionEvent as DomainNewsInteractionEvent,
    RawArticle as DomainRawArticle,
    UserNewsTaste as DomainUserNewsTaste,
)
from app.modules.news.domain.interfaces.repository import INewsRepository
from app.modules.news.recommendation.constants import (
    TRENDING_LOOKBACK_H,
    TRENDING_MIN_UNIQUE_USERS,
)
from app.modules.news.domain.value_objects import IntelligenceStatus

# Interaction types that count toward trending velocity.
_TRENDING_INTERACTION_TYPES = frozenset({"open_article", "dwell", "like", "share_tap"})
from app.modules.news.data.models import (
    EnrichedArticle,
    FeedRankingCache,
    NewsArticleStats,
    NewsInteractionEvent,
    NewsLike,
    NewsSave,
    NewsShare,
    NewsTrending,
    NewsView,
    RawArticle,
    UserNewsTaste,
    UserNewsTasteProfile,
)

CACHE_TTL_HOURS = 2


# ── ORM ↔ domain converters ────────────────────────────────────────────────────

def _raw_to_domain(row: RawArticle) -> DomainRawArticle:
    return DomainRawArticle(
        id=row.id,
        external_id=row.external_id,
        title=row.title,
        description=row.description,
        content=row.content,
        article_url=row.article_url,
        image_url=row.image_url,
        published_at=row.published_at,
        language=row.language,
        source_name=row.source_name,
        source_url=row.source_url,
        source_country=row.source_country,
        authors=list(row.authors) if row.authors else [],
        is_duplicate=row.is_duplicate,
        api_summary=row.api_summary,
        raw_metadata=row.raw_metadata,
        intelligence_status=IntelligenceStatus(row.intelligence_status),
        platform_arrived_at=row.platform_arrived_at,
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _enriched_to_domain(row: EnrichedArticle) -> DomainEnrichedArticle:
    return DomainEnrichedArticle(
        id=row.id,
        raw_article_id=row.raw_article_id,
        primary_factor=row.primary_factor,
        factor_scores=row.factor_scores,
        geo_category=row.geo_category,
        is_government=row.is_government,
        commodity_tags=row.commodity_tags,
        state_tags=row.state_tags,
        location_city=row.location_city,
        location_state=row.location_state,
        latitude=row.latitude,
        longitude=row.longitude,
        summary_bullets=row.summary_bullets,
        summary_long=row.summary_long,
        impact_direction=row.impact_direction,
        impact_score=row.impact_score,
        impact_factor=row.impact_factor,
        impact_explanation=row.impact_explanation,
        role_trader=row.role_trader,
        role_broker=row.role_broker,
        role_exporter=row.role_exporter,
        model_version=row.model_version,
        generated_at=row.generated_at,
        created_at=row.created_at,
    )


def _stats_to_domain(row: NewsArticleStats) -> DomainNewsArticleStats:
    return DomainNewsArticleStats(
        article_id=row.article_id,
        view_count=row.view_count,
        like_count=row.like_count,
        save_count=row.save_count,
        share_count=row.share_count,
        updated_at=row.updated_at,
    )


def _cache_to_domain(row: FeedRankingCache) -> DomainFeedRankingCache:
    return DomainFeedRankingCache(
        id=row.id,
        profile_id=row.profile_id,
        feed_type=row.feed_type,
        ranked_article_ids=[UUID(a) for a in (row.ranked_article_ids or [])],
        computed_at=row.computed_at,
        expires_at=row.expires_at,
    )


# ── Repository ────────────────────────────────────────────────────────────────

class NewsRepository(INewsRepository):

    def __init__(self, db: Session) -> None:
        self._db = db

    # ── Transaction control ───────────────────────────────────────────────────

    @property
    def session(self) -> Session:
        """Escape hatch for cross-module helpers that still take a Session
        (e.g. app.recommendation.amplify.commodity_ids_for)."""
        return self._db

    def commit(self) -> None:
        self._db.commit()

    def rollback(self) -> None:
        self._db.rollback()

    # ── Ingestion ─────────────────────────────────────────────────────────────

    def save_raw_article(self, article: DomainRawArticle) -> DomainRawArticle:
        stmt = (
            pg_insert(RawArticle)
            .values(
                id=article.id,
                external_id=article.external_id,
                title=article.title,
                description=article.description,
                content=article.content,
                article_url=article.article_url,
                image_url=article.image_url,
                published_at=article.published_at,
                language=article.language,
                source_name=article.source_name,
                source_url=article.source_url,
                source_country=article.source_country,
                authors=article.authors or [],
                is_duplicate=article.is_duplicate,
                api_summary=article.api_summary,
                raw_metadata=article.raw_metadata,
                intelligence_status=article.intelligence_status.value,
                platform_arrived_at=article.platform_arrived_at,
                is_active=article.is_active,
                created_at=article.created_at,
                updated_at=article.updated_at,
            )
            .on_conflict_do_nothing(index_elements=["external_id"])
        )
        self._db.execute(stmt)
        self._db.commit()
        row = self._db.execute(
            select(RawArticle).where(RawArticle.external_id == article.external_id)
        ).scalar_one()
        return _raw_to_domain(row)

    def get_pending_raw_articles(self, limit: int) -> list[DomainRawArticle]:
        rows = self._db.execute(
            select(RawArticle)
            .where(RawArticle.intelligence_status == IntelligenceStatus.PENDING.value)
            .limit(limit)
        ).scalars().all()
        return [_raw_to_domain(r) for r in rows]

    def mark_intelligence_status(
        self, article_id: UUID, status: IntelligenceStatus
    ) -> None:
        self._db.execute(
            update(RawArticle)
            .where(RawArticle.id == article_id)
            .values(
                intelligence_status=status.value,
                updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )

    def get_ingestion_stats(self) -> dict:
        rows = self._db.execute(
            select(RawArticle.intelligence_status, func.count().label("cnt"))
            .group_by(RawArticle.intelligence_status)
        ).all()
        return {r.intelligence_status: r.cnt for r in rows}

    def archive_old_raw_articles(self, days_old: int = 30) -> int:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days_old)
        result = self._db.execute(
            update(RawArticle)
            .where(RawArticle.platform_arrived_at < cutoff, RawArticle.is_active.is_(True))
            .values(is_active=False)
        )
        self._db.commit()
        return result.rowcount

    # ── Intelligence ──────────────────────────────────────────────────────────

    def save_enriched_article(self, article: DomainEnrichedArticle) -> None:
        stmt = (
            pg_insert(EnrichedArticle)
            .values(
                id=article.id,
                raw_article_id=article.raw_article_id,
                primary_factor=article.primary_factor,
                factor_scores=article.factor_scores,
                geo_category=article.geo_category,
                is_government=article.is_government,
                commodity_tags=article.commodity_tags,
                state_tags=article.state_tags,
                location_city=article.location_city,
                location_state=article.location_state,
                latitude=article.latitude,
                longitude=article.longitude,
                summary_bullets=article.summary_bullets,
                summary_long=article.summary_long,
                impact_direction=article.impact_direction,
                impact_score=article.impact_score,
                impact_factor=article.impact_factor,
                impact_explanation=article.impact_explanation,
                role_trader=article.role_trader,
                role_broker=article.role_broker,
                role_exporter=article.role_exporter,
                model_version=article.model_version,
                generated_at=article.generated_at,
                created_at=article.created_at,
            )
            .on_conflict_do_update(
                index_elements=["raw_article_id"],
                set_={
                    "primary_factor": article.primary_factor,
                    "factor_scores": article.factor_scores,
                    "geo_category": article.geo_category,
                    "is_government": article.is_government,
                    "commodity_tags": article.commodity_tags,
                    "state_tags": article.state_tags,
                    "location_city": article.location_city,
                    "location_state": article.location_state,
                    "latitude": article.latitude,
                    "longitude": article.longitude,
                    "summary_bullets": article.summary_bullets,
                    "summary_long": article.summary_long,
                    "impact_direction": article.impact_direction,
                    "impact_score": article.impact_score,
                    "impact_factor": article.impact_factor,
                    "impact_explanation": article.impact_explanation,
                    "role_trader": article.role_trader,
                    "role_broker": article.role_broker,
                    "role_exporter": article.role_exporter,
                    "model_version": article.model_version,
                    "generated_at": article.generated_at,
                },
            )
        )
        self._db.execute(stmt)
        self._db.commit()

    # ── Article existence / lookup ────────────────────────────────────────────

    def article_exists(self, article_id: UUID) -> bool:
        result = self._db.execute(
            select(RawArticle.id).where(RawArticle.id == article_id)
        ).first()
        return result is not None

    def filter_valid_article_ids(self, article_ids: list[UUID]) -> set[UUID]:
        if not article_ids:
            return set()
        rows = self._db.execute(
            select(RawArticle.id).where(RawArticle.id.in_(article_ids))
        ).scalars().all()
        return set(rows)

    def get_primary_factor_for_article(self, article_id: UUID) -> str | None:
        result = self._db.execute(
            select(EnrichedArticle.primary_factor)
            .where(EnrichedArticle.raw_article_id == article_id)
        ).scalar_one_or_none()
        return result

    # ── Views ─────────────────────────────────────────────────────────────────

    def upsert_view(self, profile_id: int, article_id: UUID) -> bool:
        existing = self._db.execute(
            select(NewsView).where(
                NewsView.profile_id == profile_id,
                NewsView.article_id == article_id,
            )
        ).scalar_one_or_none()

        if existing is not None:
            existing.view_count += 1
            existing.last_viewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            return True

        self._db.add(
            NewsView(
                profile_id=profile_id,
                article_id=article_id,
                view_count=1,
                first_viewed_at=datetime.now(timezone.utc).replace(tzinfo=None),
                last_viewed_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        return False

    # ── Like ──────────────────────────────────────────────────────────────────

    def toggle_like(self, profile_id: int, article_id: UUID) -> bool:
        existing = self._db.execute(
            select(NewsLike).where(
                NewsLike.profile_id == profile_id,
                NewsLike.article_id == article_id,
            )
        ).scalar_one_or_none()

        if existing is not None:
            self._db.delete(existing)
            return False

        self._db.add(NewsLike(profile_id=profile_id, article_id=article_id))
        return True

    # ── Save ──────────────────────────────────────────────────────────────────

    def toggle_save(self, profile_id: int, article_id: UUID) -> bool:
        existing = self._db.execute(
            select(NewsSave).where(
                NewsSave.profile_id == profile_id,
                NewsSave.article_id == article_id,
            )
        ).scalar_one_or_none()

        if existing is not None:
            self._db.delete(existing)
            return False

        self._db.add(NewsSave(profile_id=profile_id, article_id=article_id))
        return True

    # ── Share ─────────────────────────────────────────────────────────────────

    def record_share(
        self, profile_id: int, article_id: UUID, platform: str | None = None
    ) -> None:
        self._db.add(
            NewsShare(profile_id=profile_id, article_id=article_id, platform=platform)
        )

    # ── Interaction events ────────────────────────────────────────────────────

    def bulk_insert_events(self, events: list[DomainNewsInteractionEvent]) -> None:
        if not events:
            return
        self._db.execute(
            NewsInteractionEvent.__table__.insert(),
            [
                {
                    "profile_id": e.profile_id,
                    "article_id": e.article_id,
                    "event_type": e.event_type,
                    "value_ms": e.value_ms,
                    "occurred_at": e.occurred_at,
                    "created_at": e.created_at,
                    "processed_at": e.processed_at,
                }
                for e in events
            ],
        )

    # ── Article stats ─────────────────────────────────────────────────────────

    def get_article_stats(self, article_id: UUID) -> DomainNewsArticleStats | None:
        row = self._db.execute(
            select(NewsArticleStats).where(NewsArticleStats.article_id == article_id)
        ).scalar_one_or_none()
        if row is None:
            return None
        return _stats_to_domain(row)

    def adjust_article_stats(self, article_id: UUID, field: str, delta: int) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        stmt = (
            pg_insert(NewsArticleStats)
            .values(
                article_id=article_id,
                view_count=0,
                like_count=0,
                save_count=0,
                share_count=0,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=["article_id"],
                set_={
                    field: getattr(NewsArticleStats, field) + delta,
                    "updated_at": now,
                },
            )
        )
        self._db.execute(stmt)

    # ── Single entity reads ───────────────────────────────────────────────────

    def get_raw_article(self, article_id: UUID) -> DomainRawArticle | None:
        row = self._db.execute(
            select(RawArticle).where(RawArticle.id == article_id)
        ).scalar_one_or_none()
        if row is None:
            return None
        return _raw_to_domain(row)

    def get_enriched_article(self, article_id: UUID) -> DomainEnrichedArticle | None:
        row = self._db.execute(
            select(EnrichedArticle).where(EnrichedArticle.raw_article_id == article_id)
        ).scalar_one_or_none()
        if row is None:
            return None
        return _enriched_to_domain(row)

    def get_like_state(self, profile_id: int, article_id: UUID) -> bool:
        result = self._db.execute(
            select(NewsLike.id).where(
                NewsLike.profile_id == profile_id,
                NewsLike.article_id == article_id,
            )
        ).first()
        return result is not None

    def get_save_state(self, profile_id: int, article_id: UUID) -> bool:
        result = self._db.execute(
            select(NewsSave.id).where(
                NewsSave.profile_id == profile_id,
                NewsSave.article_id == article_id,
            )
        ).first()
        return result is not None

    # ── Taste ─────────────────────────────────────────────────────────────────

    def upsert_taste(
        self,
        profile_id: int,
        dimension_type: str,
        dimension_key: str,
        positive_delta: float,
        negative_delta: float = 0.0,
        event_count: int = 1,
    ) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        stmt = (
            pg_insert(UserNewsTaste)
            .values(
                profile_id=profile_id,
                dimension_type=dimension_type,
                dimension_key=dimension_key,
                positive_score=positive_delta,
                negative_score=negative_delta,
                event_count=event_count,
                last_event_at=now,
            )
            .on_conflict_do_update(
                index_elements=["profile_id", "dimension_type", "dimension_key"],
                set_={
                    "positive_score": UserNewsTaste.positive_score + positive_delta,
                    "negative_score": UserNewsTaste.negative_score + negative_delta,
                    "event_count": UserNewsTaste.event_count + event_count,
                    "last_event_at": now,
                },
            )
        )
        self._db.execute(stmt)

    # ── Feed ranking cache ────────────────────────────────────────────────────

    def get_feed_ranking_cache(
        self, profile_id: int, feed_type: str = "default"
    ) -> DomainFeedRankingCache | None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        row = self._db.execute(
            select(FeedRankingCache).where(
                FeedRankingCache.profile_id == profile_id,
                FeedRankingCache.feed_type == feed_type,
                FeedRankingCache.expires_at > now,
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return _cache_to_domain(row)

    def upsert_feed_ranking_cache(
        self,
        profile_id: int,
        ranked_article_ids: list[UUID],
        feed_type: str = "default",
    ) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        expires_at = now + timedelta(hours=CACHE_TTL_HOURS)
        ids_as_str = [str(a) for a in ranked_article_ids]
        stmt = (
            pg_insert(FeedRankingCache)
            .values(
                profile_id=profile_id,
                feed_type=feed_type,
                ranked_article_ids=ids_as_str,
                computed_at=now,
                expires_at=expires_at,
            )
            .on_conflict_do_update(
                constraint="uq_news_feed_cache_profile_type",
                set_={
                    "ranked_article_ids": ids_as_str,
                    "computed_at": now,
                    "expires_at": expires_at,
                },
            )
        )
        self._db.execute(stmt)
        self._db.commit()

    def invalidate_feed_ranking_cache(
        self, profile_id: int, feed_type: str = "default"
    ) -> None:
        self._db.execute(
            delete(FeedRankingCache).where(
                FeedRankingCache.profile_id == profile_id,
                FeedRankingCache.feed_type == feed_type,
            )
        )
        self._db.commit()

    # ── Trending snapshot ─────────────────────────────────────────────────────

    def recalc_trending(self) -> int:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        cutoff = now - timedelta(hours=TRENDING_LOOKBACK_H)

        # Count distinct profiles per article in the lookback window
        rows = self._db.execute(
            select(
                NewsInteractionEvent.article_id,
                func.count(NewsInteractionEvent.profile_id.distinct()).label("unique_profiles"),
            )
            .where(
                NewsInteractionEvent.occurred_at >= cutoff,
                NewsInteractionEvent.event_type.in_(_TRENDING_INTERACTION_TYPES),
            )
            .group_by(NewsInteractionEvent.article_id)
            .having(
                func.count(NewsInteractionEvent.profile_id.distinct())
                >= TRENDING_MIN_UNIQUE_USERS
            )
        ).all()

        if not rows:
            self._db.execute(NewsTrending.__table__.delete())
            self._db.commit()
            return 0

        # Replace the entire snapshot atomically: drop stale rows, then bulk insert
        self._db.execute(NewsTrending.__table__.delete())

        max_unique = max(r.unique_profiles for r in rows)

        self._db.execute(
            NewsTrending.__table__.insert(),
            [
                {
                    "article_id": r.article_id,
                    "velocity_score": r.unique_profiles / max(max_unique, 1),
                    "unique_profiles": r.unique_profiles,
                    "computed_at": now,
                }
                for r in rows
            ],
        )
        self._db.commit()
        return len(rows)
