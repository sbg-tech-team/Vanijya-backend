"""drop_is_verified_from_profile

Revision ID: bcac10e40984
Revises: d0e1f2a3b4c5
Create Date: 2026-05-20 15:54:58.329249

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bcac10e40984'
down_revision: Union[str, None] = 'd0e1f2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('profile', 'is_verified')


def downgrade() -> None:
    op.add_column('profile', sa.Column('is_verified', sa.BOOLEAN(), autoincrement=False, nullable=False, server_default='false'))
