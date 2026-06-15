"""add first_message to message_requests

Revision ID: k2l3m4n5o6p7
Revises: j1k2l3m4n5o6
Create Date: 2026-06-15

The connections message request is the canonical "request to chat" gate. A sender
may now attach an opening line to the request; on accept it is seeded as the first
message of the DM conversation. Nullable so a bare connect (no message) still works.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "k2l3m4n5o6p7"
down_revision: Union[str, None] = "j1k2l3m4n5o6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "message_requests",
        sa.Column("first_message", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("message_requests", "first_message")
