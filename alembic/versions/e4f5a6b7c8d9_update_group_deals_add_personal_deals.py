"""update group_deals and add personal_deals table

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-06-05

Changes
-------
group_deals:
  - add image_urls TEXT[] nullable

personal_deals (new table):
  - mirrors PostDealDetails fields exactly (grain_type, grain_size, commodity_quantity,
    quantity_unit, commodity_price, price_type, is_closed) plus image_urls
  - scoped to a DM conversation instead of a group
  - no post_id (personal deals cannot be promoted to the public feed)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e4f5a6b7c8d9"
down_revision: Union[str, None] = "d3e4f5a6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── group_deals: add image_urls ────────────────────────────────────────────
    op.add_column("group_deals", sa.Column("image_urls", postgresql.ARRAY(sa.Text()), nullable=True))

    # ── personal_deals: new table ──────────────────────────────────────────────
    op.create_table(
        "personal_deals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("posted_by", sa.UUID(), nullable=False),
        sa.Column("commodity_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("caption", sa.Text(), nullable=False),
        sa.Column("grain_type", sa.String(50), nullable=False),
        sa.Column("grain_size", sa.String(50), nullable=False),
        sa.Column("commodity_quantity", sa.Numeric(12, 2), nullable=False),
        sa.Column("quantity_unit", sa.String(20), nullable=False),
        sa.Column("commodity_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("price_type", sa.String(20), nullable=False),
        sa.Column("image_urls", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("is_closed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["commodity_id"], ["commodities.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("idx_pd_conversation_created", "personal_deals", ["conversation_id", "created_at"])
    op.create_index("idx_pd_posted_by", "personal_deals", ["posted_by"])


def downgrade() -> None:
    op.drop_index("idx_pd_posted_by", table_name="personal_deals")
    op.drop_index("idx_pd_conversation_created", table_name="personal_deals")
    op.drop_table("personal_deals")

    op.drop_column("group_deals", "image_urls")
