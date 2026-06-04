"""add post_feed_vector to user_embeddings

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-06-03

Adds a 10-dim post feed vector column to user_embeddings.
Stored at profile create/update; loaded in get_recommended_posts
instead of rebuilding from profile fields on every feed call.
Existing rows will have NULL and fall back to inline build until
the profile is next updated.
"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = 'c2d3e4f5a6b7'
down_revision = 'b1c2d3e4f5a6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'user_embeddings',
        sa.Column('post_feed_vector', Vector(10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('user_embeddings', 'post_feed_vector')
