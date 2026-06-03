"""add location and source_url to posts

Revision ID: b1c2d3e4f5a6
Revises: a8b9c0d1e2f3
Create Date: 2026-06-03

Adds three location columns and one source link column to the posts table:
  - source_url    : optional URL to an external information source
  - location_name : human-readable place label (city / market / area)
  - latitude      : overrides author business location in recommendation geo vector
  - longitude     : overrides author business location in recommendation geo vector
"""
from alembic import op
import sqlalchemy as sa

revision = 'b1c2d3e4f5a6'
down_revision = 'b9c0d1e2f3a4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('posts', sa.Column('source_url',    sa.String(500), nullable=True))
    op.add_column('posts', sa.Column('location_name', sa.String(200), nullable=True))
    op.add_column('posts', sa.Column('latitude',      sa.Float(),     nullable=True))
    op.add_column('posts', sa.Column('longitude',     sa.Float(),     nullable=True))


def downgrade() -> None:
    op.drop_column('posts', 'longitude')
    op.drop_column('posts', 'latitude')
    op.drop_column('posts', 'location_name')
    op.drop_column('posts', 'source_url')
