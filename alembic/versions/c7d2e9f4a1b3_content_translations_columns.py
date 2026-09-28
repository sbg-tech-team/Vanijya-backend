"""translations JSONB on posts, post_comments, news_raw_articles

Revision ID: c7d2e9f4a1b3
Revises: b8e1f5c02a47
Create Date: 2026-09-25

On-command translation of posts, comments and news. A translation is stored
on the item it translates, {lang: {field: {"h": source_hash, "v": text}}}, so
the next reader of that language reads it from the row instead of paying for
another engine call, and deleting the item deletes its translations.

Nullable with no default: adding the columns rewrites nothing, and an item
nobody has translated costs no storage.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c7d2e9f4a1b3"
down_revision = "b8e1f5c02a47"
branch_labels = None
depends_on = None

_TABLES = ("posts", "post_comments", "news_raw_articles")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column("translations", postgresql.JSONB(), nullable=True),
            if_not_exists=True,
        )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "translations", if_exists=True)
