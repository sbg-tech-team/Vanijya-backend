"""
SQLAlchemy ORM models for the news module.

All 12 tables in one file. Do not import from application/ or presentation/.
FK targets: "profile.id" (auth module), "news_raw_articles.id" (own module).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, Integer, String,
    Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database.base import Base

_utcnow = lambda: datetime.now(timezone.utc).replace(tzinfo=None)  # noqa: E731


# ── Ingestion ─────────────────────────────────────────────────────────────────

class RawArticle(Base):
    __tablename__ = "news_raw_articles"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    external_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    article_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_country: Mapped[str | None] = mapped_column(String(80), nullable=True)
    authors: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    api_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    intelligence_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    platform_arrived_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("ix_news_raw_articles_status", "intelligence_status"),
        Index("ix_news_raw_articles_published_at", "published_at"),
        Index("ix_news_raw_articles_arrived_at", "platform_arrived_at"),
    )


# ── Intelligence ──────────────────────────────────────────────────────────────

class EnrichedArticle(Base):
    __tablename__ = "news_enriched_articles"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    raw_article_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("news_raw_articles.id", ondelete="CASCADE"),
        nullable=False, unique=True,
    )
    primary_factor: Mapped[str] = mapped_column(String(40), nullable=False)
    factor_scores: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    geo_category: Mapped[str] = mapped_column(String(20), nullable=False)
    is_government: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    commodity_tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    state_tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    location_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    location_state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary_bullets: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    summary_long: Mapped[str | None] = mapped_column(Text, nullable=True)
    impact_direction: Mapped[str] = mapped_column(String(20), nullable=False)
    impact_score: Mapped[float] = mapped_column(Float, nullable=False)
    impact_factor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    impact_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    role_trader: Mapped[float] = mapped_column(Float, nullable=False)
    role_broker: Mapped[float] = mapped_column(Float, nullable=False)
    role_exporter: Mapped[float] = mapped_column(Float, nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# ── Interactions ──────────────────────────────────────────────────────────────

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


# ── Taste ─────────────────────────────────────────────────────────────────────

class UserNewsTaste(Base):
    __tablename__ = "user_news_taste"

    profile_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("profile.id", ondelete="CASCADE"), primary_key=True
    )
    dimension_type: Mapped[str] = mapped_column(String(20), primary_key=True)
    dimension_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    positive_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    negative_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_event_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (Index("ix_unt_profile_type", "profile_id", "dimension_type"),)


class UserNewsTasteProfile(Base):
    """Planned feature — bootstrapped summary. Table reserved for Layer 3."""
    __tablename__ = "user_news_taste_profiles"

    profile_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("profile.id", ondelete="CASCADE"), primary_key=True
    )
    dominant_factor: Mapped[str | None] = mapped_column(String(40), nullable=True)
    factor_weights: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    total_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bootstrapped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


# ── Trending ──────────────────────────────────────────────────────────────────

class NewsTrending(Base):
    """Platform-wide trending snapshot. Recomputed by recommendation/jobs/recalc_trending.py."""
    __tablename__ = "news_raw_trending"

    article_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("news_raw_articles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    velocity_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    unique_profiles: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    computed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (Index("ix_nrt_velocity_score", "velocity_score"),)


# ── Feed ranking cache ────────────────────────────────────────────────────────

class FeedRankingCache(Base):
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
