"""add_group_join_requests_table

Revision ID: a8b9c0d1e2f3
Revises: f2a3b4c5d6e7
Create Date: 2026-05-28

Changes
-------
group_join_requests:
  - new table for tracking join requests to private groups
  - status: pending | approved | rejected
  - admin resolves via approve/reject endpoints
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "group_join_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Fast lookup: all pending requests for a group (admin dashboard)
    op.create_index("idx_gjr_group_status", "group_join_requests", ["group_id", "status"])
    # Fast lookup: requests submitted by a user
    op.create_index("idx_gjr_user", "group_join_requests", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_gjr_user", table_name="group_join_requests")
    op.drop_index("idx_gjr_group_status", table_name="group_join_requests")
    op.drop_table("group_join_requests")
