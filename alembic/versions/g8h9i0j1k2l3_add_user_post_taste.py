"""add user_post_taste table

Revision ID: g8h9i0j1k2l3
Revises: f7a8b9c0d1e2
Create Date: 2026-06-05

New tables
----------
user_post_taste  – row-per-dimension persistent taste store (Phase 3).
                   Replaces user_taste_profiles as the active recommendation
                   read path in Phase 7.

Composite PK: (profile_id, dimension_type, dimension_key)
Index: ix_upt_profile_type on (profile_id, dimension_type)

Data migration
--------------
Existing rows in user_taste_profiles are converted to category-type rows
in user_post_taste (only categories with count > 0 are migrated).

user_taste_profiles is NOT dropped here — it remains the active reranker
read path until Phase 7.  Drop it in a later migration once Phase 7 is stable.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'g8h9i0j1k2l3'
down_revision: Union[str, None] = 'f7a8b9c0d1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_post_taste",
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("dimension_type", sa.String(20), nullable=False),
        sa.Column("dimension_key", sa.String(50), nullable=False),
        sa.Column("positive_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("negative_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("event_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("profile_id", "dimension_type", "dimension_key"),
        sa.ForeignKeyConstraint(["profile_id"], ["profile.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_upt_profile_type",
        "user_post_taste",
        ["profile_id", "dimension_type"],
    )

    # ── Data migration ────────────────────────────────────────────────────────
    # Convert existing user_taste_profiles category counts to float rows.
    # Only inserts categories where the count > 0. Uses ON CONFLICT DO NOTHING
    # so the migration is safe to re-run.
    op.execute("""
        INSERT INTO user_post_taste
            (profile_id, dimension_type, dimension_key,
             positive_score, negative_score, event_count, last_event_at)
        SELECT
            profile_id,
            'category',
            'market_update',
            CAST(market_update_count AS DOUBLE PRECISION),
            0.0,
            market_update_count,
            updated_at
        FROM user_taste_profiles
        WHERE market_update_count > 0
        ON CONFLICT DO NOTHING
    """)
    op.execute("""
        INSERT INTO user_post_taste
            (profile_id, dimension_type, dimension_key,
             positive_score, negative_score, event_count, last_event_at)
        SELECT
            profile_id,
            'category',
            'deal_req',
            CAST(deal_req_count AS DOUBLE PRECISION),
            0.0,
            deal_req_count,
            updated_at
        FROM user_taste_profiles
        WHERE deal_req_count > 0
        ON CONFLICT DO NOTHING
    """)
    op.execute("""
        INSERT INTO user_post_taste
            (profile_id, dimension_type, dimension_key,
             positive_score, negative_score, event_count, last_event_at)
        SELECT
            profile_id,
            'category',
            'discussion',
            CAST(discussion_count AS DOUBLE PRECISION),
            0.0,
            discussion_count,
            updated_at
        FROM user_taste_profiles
        WHERE discussion_count > 0
        ON CONFLICT DO NOTHING
    """)
    op.execute("""
        INSERT INTO user_post_taste
            (profile_id, dimension_type, dimension_key,
             positive_score, negative_score, event_count, last_event_at)
        SELECT
            profile_id,
            'category',
            'knowledge',
            CAST(knowledge_count AS DOUBLE PRECISION),
            0.0,
            knowledge_count,
            updated_at
        FROM user_taste_profiles
        WHERE knowledge_count > 0
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.drop_index("ix_upt_profile_type", table_name="user_post_taste")
    op.drop_table("user_post_taste")
