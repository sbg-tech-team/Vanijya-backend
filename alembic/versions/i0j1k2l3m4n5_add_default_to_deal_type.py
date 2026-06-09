"""add default and nullable to group_deals.deal_type

Revision ID: i0j1k2l3m4n5
Revises: h9i0j1k2l3m4
Create Date: 2026-06-09

deal_type exists in the DB with NOT NULL but no default and no matching
ORM field.  Every INSERT from the ORM omits it, which triggered a
NotNullViolation.  This migration documents the manual Supabase fix:
  - server default set to 'selling'
  - column made nullable
so a fresh DB rebuild stays in sync with the live instance.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "i0j1k2l3m4n5"
down_revision: Union[str, None] = "h9i0j1k2l3m4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "group_deals",
        "deal_type",
        existing_type=sa.String(50),
        nullable=True,
        server_default="selling",
    )


def downgrade() -> None:
    op.alter_column(
        "group_deals",
        "deal_type",
        existing_type=sa.String(50),
        nullable=False,
        server_default=None,
    )
