import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, String, Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database.base import Base


class EnrichedArticle(Base):
    """
    The enriched (intelligent) view of a raw article — one row per RawArticle.
    Maps the Groq pipeline output 1:1: classification + summary + impact, plus
    role_relevance copied from the matrix at enrich time.

    Slice-decoupled: references the raw row by FK *table name*, never by
    importing the ingestion ORM class.
    """
    __tablename__ = "news_enriched_articles"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    raw_article_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("news_raw_articles.id", ondelete="CASCADE"),
        nullable=False, unique=True,
    )

    # ── Classification ───────────────────────────────────────────────────────
    primary_factor: Mapped[str] = mapped_column(String(40), nullable=False)  # one of the 10 slugs
    factor_scores: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # [{factor, score}], top 2-3
    geo_category: Mapped[str] = mapped_column(String(20), nullable=False)     # global|domestic
    # Independent axis: is this primarily a government/regulator/policy story? (any country)
    is_government: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── Summary (OUR generated bullets; provider summary stays on RawArticle) ─
    summary_bullets: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # ["...", "...", "..."]
    summary_long: Mapped[str | None] = mapped_column(Text, nullable=True)       # optional paragraph

    # ── Impact (objective market sentiment; one value for everyone for now) ───
    impact_direction: Mapped[str] = mapped_column(String(20), nullable=False)  # positive|neutral|negative
    impact_score: Mapped[float] = mapped_column(Float, nullable=False)         # 0-10 magnitude
    impact_factor: Mapped[str | None] = mapped_column(String(120), nullable=True)   # short label
    impact_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)     # one sentence

    # ── Role relevance — COMPUTED from the matrix, never from the LLM ─────────
    role_trader: Mapped[float] = mapped_column(Float, nullable=False)
    role_broker: Mapped[float] = mapped_column(Float, nullable=False)
    role_exporter: Mapped[float] = mapped_column(Float, nullable=False)

    model_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
