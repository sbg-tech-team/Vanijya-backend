"""add commodity_tags and state_tags to news_enriched_articles

Revision ID: p7q8r9s0t1u2
Revises: 2e5f1a7c9b40
Create Date: 2026-06-25

Layer 2 profile scoring requires commodity mentions and Indian state mentions to
be extracted by the LLM and stored per enriched article. Existing rows get NULL
(treated as [] in application code); new enrichments populate both columns.
Additive, non-destructive.
"""
from __future__ import annotations

from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "p7q8r9s0t1u2"
down_revision: Union[str, None] = "o6p7q8r9s0t1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "news_enriched_articles",
        sa.Column("commodity_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "news_enriched_articles",
        sa.Column("state_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("news_enriched_articles", "state_tags")
    op.drop_column("news_enriched_articles", "commodity_tags")
