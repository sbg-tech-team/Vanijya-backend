"""add article_id to messages

Revision ID: o6p7q8r9s0t1
Revises: 2e5f1a7c9b40
Create Date: 2026-06-24

Additive, non-destructive: adds a nullable article_id UUID FK to the messages
table so that 'news_article' message_type payloads can reference a raw article.
SET NULL on delete — if the article is soft-deleted or purged the message shell
survives (same pattern as post_id).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "o6p7q8r9s0t1"
down_revision = "2e5f1a7c9b40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("news_raw_articles.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_messages_article_id", "messages", ["article_id"])


def downgrade() -> None:
    op.drop_index("ix_messages_article_id", table_name="messages")
    op.drop_column("messages", "article_id")
