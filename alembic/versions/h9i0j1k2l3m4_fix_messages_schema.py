"""fix messages and chat_attachments schema to match ORM models

Revision ID: h9i0j1k2l3m4
Revises: g8h9i0j1k2l3
Create Date: 2026-06-09

Changes
-------
messages:
  - drop media_url (VARCHAR 500, single URL) → add media_urls TEXT[] nullable
  - rename created_at → sent_at  (also rebuilds the context index)
  - add deal_id       UUID FK → group_deals.id    ON DELETE SET NULL
  - add personal_deal_id UUID FK → personal_deals.id ON DELETE SET NULL
  - add post_id       INTEGER FK → posts.id         ON DELETE SET NULL

chat_attachments:
  - add storage_path VARCHAR(500) nullable
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "h9i0j1k2l3m4"
down_revision: Union[str, None] = "g8h9i0j1k2l3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── messages: media_url → media_urls ──────────────────────────────────────
    op.drop_column("messages", "media_url")
    op.add_column(
        "messages",
        sa.Column("media_urls", postgresql.ARRAY(sa.Text()), nullable=True),
    )

    # ── messages: created_at → sent_at ────────────────────────────────────────
    # Drop the index that references created_at before renaming the column.
    op.drop_index("idx_messages_context", table_name="messages")
    op.alter_column("messages", "created_at", new_column_name="sent_at")
    op.create_index(
        "idx_messages_context",
        "messages",
        ["context_type", "context_id", sa.text("sent_at DESC")],
    )

    # ── messages: add deal_id FK ───────────────────────────────────────────────
    op.add_column(
        "messages",
        sa.Column("deal_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_messages_deal_id",
        "messages", "group_deals",
        ["deal_id"], ["id"],
        ondelete="SET NULL",
    )

    # ── messages: add personal_deal_id FK ─────────────────────────────────────
    op.add_column(
        "messages",
        sa.Column("personal_deal_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_messages_personal_deal_id",
        "messages", "personal_deals",
        ["personal_deal_id"], ["id"],
        ondelete="SET NULL",
    )

    # ── messages: add post_id FK ───────────────────────────────────────────────
    op.add_column(
        "messages",
        sa.Column("post_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_messages_post_id",
        "messages", "posts",
        ["post_id"], ["id"],
        ondelete="SET NULL",
    )

    # ── chat_attachments: add storage_path ────────────────────────────────────
    op.add_column(
        "chat_attachments",
        sa.Column("storage_path", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    # ── chat_attachments ──────────────────────────────────────────────────────
    op.drop_column("chat_attachments", "storage_path")

    # ── messages: drop post_id ────────────────────────────────────────────────
    op.drop_constraint("fk_messages_post_id", "messages", type_="foreignkey")
    op.drop_column("messages", "post_id")

    # ── messages: drop personal_deal_id ───────────────────────────────────────
    op.drop_constraint("fk_messages_personal_deal_id", "messages", type_="foreignkey")
    op.drop_column("messages", "personal_deal_id")

    # ── messages: drop deal_id ────────────────────────────────────────────────
    op.drop_constraint("fk_messages_deal_id", "messages", type_="foreignkey")
    op.drop_column("messages", "deal_id")

    # ── messages: sent_at → created_at ────────────────────────────────────────
    op.drop_index("idx_messages_context", table_name="messages")
    op.alter_column("messages", "sent_at", new_column_name="created_at")
    op.create_index(
        "idx_messages_context",
        "messages",
        ["context_type", "context_id", sa.text("created_at DESC")],
    )

    # ── messages: media_urls → media_url ──────────────────────────────────────
    op.drop_column("messages", "media_urls")
    op.add_column(
        "messages",
        sa.Column("media_url", sa.String(500), nullable=True),
    )
