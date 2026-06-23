"""news_new raw + enriched articles

Revision ID: 1373b3c3b0de
Revises: m4n5o6p7q8r9
Create Date: 2026-06-22

Owns the two core news_new tables: news_raw_articles (canonical raw store) and
news_enriched_articles (1:1 enrichment). The remaining 11 interaction/ranking
tables are added by n5o6p7q8r9s0; is_government is added by 2e5f1a7c9b40.
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "1373b3c3b0de"
down_revision: Union[str, None] = "m4n5o6p7q8r9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── news_raw_articles ─────────────────────────────────────────────────────
    op.create_table(
        "news_raw_articles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_id", sa.String(128), nullable=False, unique=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("content", sa.Text, nullable=True),
        sa.Column("article_url", sa.String(1000), nullable=False),
        sa.Column("image_url", sa.String(1000), nullable=True),
        sa.Column("published_at", sa.DateTime, nullable=False),
        sa.Column("language", sa.String(20), nullable=True),
        sa.Column("source_name", sa.String(200), nullable=True),
        sa.Column("source_url", sa.String(500), nullable=True),
        sa.Column("source_country", sa.String(80), nullable=True),
        sa.Column("authors", postgresql.ARRAY(sa.String), nullable=True),
        sa.Column("is_duplicate", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("api_summary", sa.Text, nullable=True),
        sa.Column("raw_metadata", postgresql.JSONB, nullable=True),
        sa.Column("intelligence_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("platform_arrived_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_news_raw_articles_status", "news_raw_articles", ["intelligence_status"])
    op.create_index("ix_news_raw_articles_published_at", "news_raw_articles", ["published_at"])
    op.create_index("ix_news_raw_articles_arrived_at", "news_raw_articles", ["platform_arrived_at"])

    # ── news_enriched_articles (is_government added later by 2e5f1a7c9b40) ─────
    op.create_table(
        "news_enriched_articles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "raw_article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("news_raw_articles.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("primary_factor", sa.String(40), nullable=False),
        sa.Column("factor_scores", postgresql.JSONB, nullable=True),
        sa.Column("geo_category", sa.String(20), nullable=False),
        sa.Column("summary_bullets", postgresql.JSONB, nullable=True),
        sa.Column("summary_long", sa.Text, nullable=True),
        sa.Column("impact_direction", sa.String(20), nullable=False),
        sa.Column("impact_score", sa.Float, nullable=False),
        sa.Column("impact_factor", sa.String(120), nullable=True),
        sa.Column("impact_explanation", sa.Text, nullable=True),
        sa.Column("role_trader", sa.Float, nullable=False),
        sa.Column("role_broker", sa.Float, nullable=False),
        sa.Column("role_exporter", sa.Float, nullable=False),
        sa.Column("model_version", sa.String(80), nullable=True),
        sa.Column("generated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("news_enriched_articles")
    op.drop_index("ix_news_raw_articles_arrived_at", table_name="news_raw_articles")
    op.drop_index("ix_news_raw_articles_published_at", table_name="news_raw_articles")
    op.drop_index("ix_news_raw_articles_status", table_name="news_raw_articles")
    op.drop_table("news_raw_articles")
