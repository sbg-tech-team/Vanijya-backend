"""drop_is_verified_from_profile

Revision ID: bcac10e40984
Revises: d0e1f2a3b4c5
Create Date: 2026-05-20 15:54:58.329249

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'bcac10e40984'
down_revision: Union[str, None] = 'd0e1f2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE profile DROP COLUMN IF EXISTS is_verified")


def downgrade() -> None:
    op.execute("ALTER TABLE profile ADD COLUMN IF NOT EXISTS is_verified BOOLEAN NOT NULL DEFAULT false")
