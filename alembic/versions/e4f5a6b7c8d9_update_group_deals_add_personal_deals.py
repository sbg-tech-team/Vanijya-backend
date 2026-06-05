"""update group_deals and add personal_deals table

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-06-05

Changes
-------
group_deals:
  - add deal_type VARCHAR(10) NOT NULL (selling | buying) with check constraint
  - add broken_percentage NUMERIC(5,2) nullable
  - add location VARCHAR(200) nullable
  - add image_urls TEXT[] nullable
  - make grain_size nullable (marked optional in UI)
  - make commodity_price nullable (buying deals have no price)
  - make price_type nullable (buying deals have no price type)

personal_deals (new table):
  - same deal fields as group_deals
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
    # ── group_deals: new columns ───────────────────────────────────────────────
    # deal_type added with server_default so existing rows get a value,
    # then the default is dropped — all future inserts must supply it explicitly.
    op.add_column("group_deals", sa.Column("deal_type", sa.String(10), nullable=False, server_default="selling"))
    op.alter_column("group_deals", "deal_type", server_default=None)

    op.add_column("group_deals", sa.Column("broken_percentage", sa.Numeric(5, 2), nullable=True))
    op.add_column("group_deals", sa.Column("location", sa.String(200), nullable=True))
    op.add_column("group_deals", sa.Column("image_urls", postgresql.ARRAY(sa.Text()), nullable=True))

    op.create_check_constraint(
        "ck_group_deals_deal_type",
        "group_deals",
        "deal_type IN ('selling', 'buying')",
    )

    # ── group_deals: make existing NOT NULL columns nullable ───────────────────
    op.alter_column("group_deals", "grain_size", nullable=True)
    op.alter_column("group_deals", "commodity_price", nullable=True)
    op.alter_column("group_deals", "price_type", nullable=True)

    # ── personal_deals: new table ──────────────────────────────────────────────
    op.create_table(
        "personal_deals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("posted_by", sa.UUID(), nullable=False),
        sa.Column("commodity_id", sa.Integer(), nullable=False),
        sa.Column("deal_type", sa.String(10), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("caption", sa.Text(), nullable=False),
        sa.Column("grain_type", sa.String(50), nullable=False),
        sa.Column("grain_size", sa.String(50), nullable=True),
        sa.Column("broken_percentage", sa.Numeric(5, 2), nullable=True),
        sa.Column("commodity_quantity", sa.Numeric(12, 2), nullable=False),
        sa.Column("quantity_unit", sa.String(20), nullable=False),
        sa.Column("commodity_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("price_type", sa.String(20), nullable=True),
        sa.Column("location", sa.String(200), nullable=True),
        sa.Column("image_urls", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("is_closed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("deal_type IN ('selling', 'buying')", name="ck_personal_deals_deal_type"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["commodity_id"], ["commodities.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("idx_pd_conversation_created", "personal_deals", ["conversation_id", "created_at"])
    op.create_index("idx_pd_posted_by", "personal_deals", ["posted_by"])


def downgrade() -> None:
    # personal_deals
    op.drop_index("idx_pd_posted_by", table_name="personal_deals")
    op.drop_index("idx_pd_conversation_created", table_name="personal_deals")
    op.drop_table("personal_deals")

    # group_deals: restore nullability
    op.alter_column("group_deals", "price_type", nullable=False)
    op.alter_column("group_deals", "commodity_price", nullable=False)
    op.alter_column("group_deals", "grain_size", nullable=False)

    op.drop_constraint("ck_group_deals_deal_type", "group_deals", type_="check")
    op.drop_column("group_deals", "image_urls")
    op.drop_column("group_deals", "location")
    op.drop_column("group_deals", "broken_percentage")
    op.drop_column("group_deals", "deal_type")
