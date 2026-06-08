"""add post_interaction_events table

Revision ID: f7a8b9c0d1e2
Revises: e4f5a6b7c8d9
Create Date: 2026-06-05

New tables
----------
post_interaction_events – append-only log of every post interaction signal
                          received from the client (impression, dwell, open_*,
                          link_click) plus server-generated revisit events.

Indexes
-------
ix_pie_profile_post        – (profile_id, post_id)   fast per-user-post lookup
ix_pie_event_type_created  – (event_type, created_at) signal derivation queries
ix_pie_created_at          – (created_at)             analytics rollup queries
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f7a8b9c0d1e2'
down_revision: Union[str, None] = 'e4f5a6b7c8d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "post_interaction_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("value_ms", sa.Integer(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["profile.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["post_id"], ["posts.id"], ondelete="CASCADE"
        ),
    )

    op.create_index(
        "ix_pie_profile_post",
        "post_interaction_events",
        ["profile_id", "post_id"],
    )
    op.create_index(
        "ix_pie_event_type_created",
        "post_interaction_events",
        ["event_type", "created_at"],
    )
    op.create_index(
        "ix_pie_created_at",
        "post_interaction_events",
        ["created_at"],
    )
    op.create_index(
        "ix_pie_event_type_processed",
        "post_interaction_events",
        ["event_type", "processed_at"],
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_pie_event_type_processed")
    op.drop_index("ix_pie_created_at", table_name="post_interaction_events")
    op.drop_index("ix_pie_event_type_created", table_name="post_interaction_events")
    op.drop_index("ix_pie_profile_post", table_name="post_interaction_events")
    op.drop_table("post_interaction_events")
