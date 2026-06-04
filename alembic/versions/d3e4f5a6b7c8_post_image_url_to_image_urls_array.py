"""post image_url to image_urls array

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-06-04

Replaces the single image_url String column on posts with image_urls VARCHAR[],
allowing up to 5 images per post. Existing rows with a non-null image_url are
migrated into a 1-element array; null rows stay null.
"""
from alembic import op
import sqlalchemy as sa

revision = 'd3e4f5a6b7c8'
down_revision = 'c2d3e4f5a6b7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'posts',
        sa.Column('image_urls', sa.ARRAY(sa.String()), nullable=True),
    )
    op.execute(
        "UPDATE posts SET image_urls = ARRAY[image_url] WHERE image_url IS NOT NULL"
    )
    op.drop_column('posts', 'image_url')


def downgrade() -> None:
    op.add_column(
        'posts',
        sa.Column('image_url', sa.String(), nullable=True),
    )
    op.execute(
        "UPDATE posts SET image_url = image_urls[1] WHERE image_urls IS NOT NULL AND array_length(image_urls, 1) > 0"
    )
    op.drop_column('posts', 'image_urls')
