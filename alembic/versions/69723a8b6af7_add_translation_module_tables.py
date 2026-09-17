"""add translation module tables

Revision ID: 69723a8b6af7
Revises: 2cd2e752e76c
Create Date: 2026-09-17

Three new tables for the translation module: a shared per-conversation rolling
summary (conversation_translation_context), per-reader-per-conversation target
language + continuous on/off (reader_conversation_translation_prefs), and each
reader's app-wide default target language (reader_translation_defaults).
Additive, non-destructive — no existing table is touched.

Originally hand-written against local main's stale head (d1e2f3a4b5c6), which
turned out to be 35 commits behind origin/main. Rebased onto the real current
head (2cd2e752e76c) after pulling.
"""
from __future__ import annotations

from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "69723a8b6af7"
down_revision: Union[str, None] = "2cd2e752e76c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_translation_context",
        sa.Column("context_type", sa.String(length=10), nullable=False),
        sa.Column("context_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("last_summarized_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("messages_since_refresh", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["last_summarized_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("context_type", "context_id"),
    )

    op.create_table(
        "reader_conversation_translation_prefs",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_lang", sa.String(length=10), nullable=True),
        sa.Column("continuous_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "conversation_id"),
    )

    op.create_table(
        "reader_translation_defaults",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_lang", sa.String(length=10), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("reader_translation_defaults")
    op.drop_table("reader_conversation_translation_prefs")
    op.drop_table("conversation_translation_context")
