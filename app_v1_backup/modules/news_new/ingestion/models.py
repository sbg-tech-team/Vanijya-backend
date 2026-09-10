import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import (
    Boolean, DateTime, Index, String, Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database.base import Base
from app.modules.news_new.config import STATUS_PENDING


class RawArticle(Base):
    """
    The canonical raw article — provider-agnostic. Every provider adapter
    (gnews, newsdata, ...) normalizes its response into this one shape.
    Intelligence reads these rows and writes a separate EnrichedArticle.

    Provider-specific fields that aren't universal live in `raw_metadata`.
    """
    __tablename__ = "news_raw_articles"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Provider's article id — dedup / upsert key.
    external_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)  # may be truncated by provider
    article_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)  # source timestamp (UTC, naive)

    language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_country: Mapped[str | None] = mapped_column(String(80), nullable=True)  # feed geo filter
    authors: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    # Provider's own AI summary, stored as-is. Independent from OUR summary.
    api_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Full provider payload, verbatim (audit / replay / re-normalize later).
    raw_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # pending -> enriched (-> failed). Drives the enrichment queue.
    intelligence_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=STATUS_PENDING
    )

    # When WE ingested it (distinct from source published_at).
    platform_arrived_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # soft feed control

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )

    __table_args__ = (
        Index("ix_news_raw_articles_status", "intelligence_status"),
        Index("ix_news_raw_articles_published_at", "published_at"),
        Index("ix_news_raw_articles_arrived_at", "platform_arrived_at"),
    )
