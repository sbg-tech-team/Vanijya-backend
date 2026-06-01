"""add_group_deals_table

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-06-01

Changes
-------
group_deals:
  - group-scoped Deal/Requirement post (category_id=4 equivalent)
  - inline deal fields mirror post_deal_details for clean future extraction
  - post_id FK allows optional promotion to the public posts feed
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "group_deals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("posted_by", sa.UUID(), nullable=False),
        sa.Column("commodity_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("caption", sa.Text(), nullable=False),
        sa.Column("grain_type", sa.String(length=50), nullable=False),
        sa.Column("grain_size", sa.String(length=50), nullable=False),
        sa.Column("commodity_quantity", sa.Numeric(12, 2), nullable=False),
        sa.Column("quantity_unit", sa.String(length=20), nullable=False),
        sa.Column("commodity_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("price_type", sa.String(length=20), nullable=False),
        sa.Column("is_closed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("post_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["commodity_id"], ["commodities.id"]),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    # List all deals for a group, newest first (primary query pattern)
    op.create_index("idx_gd_group_created", "group_deals", ["group_id", "created_at"])
    # Find all deals posted by a user
    op.create_index("idx_gd_posted_by", "group_deals", ["posted_by"])
    # Find the promoted post for a deal
    op.create_index("idx_gd_post_id", "group_deals", ["post_id"])


def downgrade() -> None:
    op.drop_index("idx_gd_post_id", table_name="group_deals")
    op.drop_index("idx_gd_posted_by", table_name="group_deals")
    op.drop_index("idx_gd_group_created", table_name="group_deals")
    op.drop_table("group_deals")
