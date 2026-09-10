import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database.base import Base

_utcnow = lambda: datetime.now(timezone.utc).replace(tzinfo=None)  # noqa: E731


class ArticleRecommendationScore(Base):
    """
    Per-profile per-article composite score. Recomputed on demand.
    final_score drives feed ranking. Phase 1: role_score only.
    Phase 2+: weighted sum of role_score + profile_score + taste_score.
    """
    __tablename__ = "news_recommendation_scores"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    profile_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("profile.id", ondelete="CASCADE"), nullable=False
    )
    article_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("news_raw_articles.id", ondelete="CASCADE"),
        nullable=False,
    )
    role_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    profile_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    taste_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    computed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    model_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    is_served: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("profile_id", "article_id", name="uq_news_rec_score_profile_article"),
        Index("ix_nrs_profile_final", "profile_id", "final_score"),
    )


class FeedRankingCache(Base):
    """
    Cached ranked article_id list per profile+feed_type.
    Invalidated when taste changes or on expiry.
    """
    __tablename__ = "news_feed_ranking_cache"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    profile_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("profile.id", ondelete="CASCADE"), nullable=False
    )
    feed_type: Mapped[str] = mapped_column(String(30), nullable=False, default="default")
    ranked_article_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("profile_id", "feed_type", name="uq_news_feed_cache_profile_type"),
        Index("ix_nfc_expires_at", "expires_at"),
    )
