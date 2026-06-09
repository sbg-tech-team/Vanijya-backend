"""add default and nullable to personal_deals.deal_type

Revision ID: j1k2l3m4n5o6
Revises: i0j1k2l3m4n5
Create Date: 2026-06-09

personal_deals.deal_type was added directly to the DB without a migration
and has no matching ORM field.  Every INSERT from the ORM omits it, which
triggers a NotNullViolation.  Make it nullable with a server default of
'selling' so Postgres fills it automatically.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "j1k2l3m4n5o6"
down_revision: Union[str, None] = "i0j1k2l3m4n5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "personal_deals",
        "deal_type",
        existing_type=sa.String(50),
        nullable=True,
        server_default="selling",
    )


def downgrade() -> None:
    op.alter_column(
        "personal_deals",
        "deal_type",
        existing_type=sa.String(50),
        nullable=False,
        server_default=None,
    )
