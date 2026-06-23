import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index,
    Integer, String, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database.base import Base

_utcnow = lambda: datetime.now(timezone.utc).replace(tzinfo=None)  # noqa: E731


class NewsInteractionEvent(Base):
    __tablename__ = "news_interaction_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("profile.id", ondelete="CASCADE"), nullable=False
    )
    article_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("news_raw_articles.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    value_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_nie_profile_article", "profile_id", "article_id"),
        Index("ix_nie_event_type_created", "event_type", "created_at"),
        Index("ix_nie_created_at", "created_at"),
        Index("ix_nie_event_type_processed", "event_type", "processed_at"),
    )


class NewsView(Base):
    """One row per profile+article; revisit detection fires on conflict."""
    __tablename__ = "news_views"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("profile.id", ondelete="CASCADE"), nullable=False
    )
    article_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("news_raw_articles.id", ondelete="CASCADE"),
        nullable=False,
    )
    first_viewed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    last_viewed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("profile_id", "article_id", name="uq_news_view_profile_article"),
        Index("ix_nv_profile_id", "profile_id"),
    )


class NewsLike(Base):
    __tablename__ = "news_likes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("profile.id", ondelete="CASCADE"), nullable=False
    )
    article_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("news_raw_articles.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("profile_id", "article_id", name="uq_news_like_profile_article"),
        Index("ix_nl_profile_id", "profile_id"),
    )


class NewsSave(Base):
    __tablename__ = "news_saves"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("profile.id", ondelete="CASCADE"), nullable=False
    )
    article_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("news_raw_articles.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("profile_id", "article_id", name="uq_news_save_profile_article"),
        Index("ix_ns_profile_id", "profile_id"),
    )


class NewsShare(Base):
    __tablename__ = "news_shares"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("profile.id", ondelete="CASCADE"), nullable=False
    )
    article_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("news_raw_articles.id", ondelete="CASCADE"),
        nullable=False,
    )
    platform: Mapped[str | None] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (Index("ix_nsh_profile_id", "profile_id"),)


class NewsArticleStats(Base):
    """Pre-computed per-article counters. One row per article, upserted by background jobs."""
    __tablename__ = "news_article_stats"

    article_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("news_raw_articles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    like_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    save_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    share_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class NewsTrending(Base):
    """Velocity-ranked trending snapshot; computed by a background job, not inline."""
    __tablename__ = "news_raw_trending"

    article_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("news_raw_articles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    velocity_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    trending_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (Index("ix_nrt_velocity_score", "velocity_score"),)


class UserNewsTaste(Base):
    """
    Persistent row-per-dimension taste signal, mirroring UserPostTaste.
    dimension_type in {category, source, tag}; dimension_key is the slug/name.
    """
    __tablename__ = "user_news_taste"

    profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("profile.id", ondelete="CASCADE"),
        primary_key=True,
    )
    dimension_type: Mapped[str] = mapped_column(String(20), primary_key=True)
    dimension_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    positive_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    negative_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_event_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (Index("ix_unt_profile_type", "profile_id", "dimension_type"),)


class UserNewsTasteProfile(Base):
    """
    Rolled-up taste summary for cold-start seeding and the recommendation engine.
    Bootstrapped once TASTE_BOOTSTRAP_EVENTS events are accumulated.
    """
    __tablename__ = "user_news_taste_profiles"

    profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("profile.id", ondelete="CASCADE"),
        primary_key=True,
    )
    dominant_factor: Mapped[str | None] = mapped_column(String(40), nullable=True)
    factor_weights: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    total_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bootstrapped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
