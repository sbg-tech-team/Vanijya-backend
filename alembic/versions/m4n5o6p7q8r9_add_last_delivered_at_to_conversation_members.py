"""add last_delivered_at to conversation_members

Revision ID: m4n5o6p7q8r9
Revises: l3m4n5o6p7q8
Create Date: 2026-06-16

Delivery high-water mark per conversation member — mirrors last_read_at. A message
is "delivered" to the peer when peer.last_delivered_at >= message.sent_at, so the
grey (delivered) tick is derived from one timestamp per member instead of a flag
per message. Nullable (no deliveries yet for existing rows).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "m4n5o6p7q8r9"
down_revision: Union[str, None] = "l3m4n5o6p7q8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversation_members",
        sa.Column("last_delivered_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversation_members", "last_delivered_at")
