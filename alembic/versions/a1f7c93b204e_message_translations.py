"""message_translations — durable translated text per (message, language)

Revision ID: a1f7c93b204e
Revises: 69723a8b6af7
Create Date: 2026-09-21

Translations previously lived only in a live socket event and a per-process
in-memory cache, so they vanished on scroll-back, thread reopen, reconnect and
restart. This gives them a home.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a1f7c93b204e"
down_revision = "69723a8b6af7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "message_translations",
        sa.Column("message_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("target_lang", sa.String(10), primary_key=True),
        sa.Column("translated_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("message_translations", if_exists=True)
