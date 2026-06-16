"""add context_type/context_id to chat_attachments

Revision ID: l3m4n5o6p7q8
Revises: k2l3m4n5o6p7
Create Date: 2026-06-16

chat_attachments.context_type and context_id exist in the live DB as NOT NULL
columns but were added manually with no matching ORM field, so every ORM insert
omitted them and hit a NotNullViolation. This migration documents them so a
fresh rebuild matches the live instance. Idempotent (IF NOT EXISTS) because the
columns already exist on the live DB.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "l3m4n5o6p7q8"
down_revision: Union[str, None] = "k2l3m4n5o6p7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS → no-op on the live DB (columns already present), adds them on a fresh build.
    op.execute("ALTER TABLE chat_attachments ADD COLUMN IF NOT EXISTS context_type VARCHAR(10)")
    op.execute("ALTER TABLE chat_attachments ADD COLUMN IF NOT EXISTS context_id UUID")
    # Backfill any rows missing the values from the parent message (covers a fresh add).
    op.execute("""
        UPDATE chat_attachments ca
        SET context_type = m.context_type,
            context_id   = m.context_id
        FROM messages m
        WHERE m.id = ca.message_id
          AND (ca.context_type IS NULL OR ca.context_id IS NULL)
    """)
    op.execute("ALTER TABLE chat_attachments ALTER COLUMN context_type SET NOT NULL")
    op.execute("ALTER TABLE chat_attachments ALTER COLUMN context_id SET NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE chat_attachments DROP COLUMN IF EXISTS context_type")
    op.execute("ALTER TABLE chat_attachments DROP COLUMN IF EXISTS context_id")
