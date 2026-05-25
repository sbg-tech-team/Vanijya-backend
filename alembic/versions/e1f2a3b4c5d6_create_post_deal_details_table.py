"""create_post_deal_details_table

Revision ID: e1f2a3b4c5d6
Revises: bcac10e40984
Create Date: 2026-05-25

Splits deal/requirement-specific fields out of the posts table into a
dedicated post_deal_details table (one-to-one with posts).
Also removes the 'Other' post category (id=5).
Truncates post_embeddings because the vector schema changed from 11D to 10D.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = 'bcac10e40984'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create post_deal_details table
    op.create_table(
        'post_deal_details',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('post_id', sa.Integer(), nullable=False),
        sa.Column('grain_type', sa.String(100), nullable=False),
        sa.Column('grain_size', sa.String(50), nullable=False),
        sa.Column('commodity_quantity', sa.Float(), nullable=False),
        sa.Column('quantity_unit', sa.String(20), nullable=False),
        sa.Column('commodity_price', sa.Float(), nullable=False),
        sa.Column('price_type', sa.String(20), nullable=False),
        sa.Column('is_closed', sa.Boolean(), nullable=False, server_default='false'),
        sa.ForeignKeyConstraint(['post_id'], ['posts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('post_id', name='uq_post_deal_details_post_id'),
    )

    # 2. Add title to posts (server_default='' covers any existing rows)
    op.add_column('posts', sa.Column('title', sa.String(200), nullable=False, server_default=''))
    op.alter_column('posts', 'title', server_default=None)  # remove default after backfill

    # 3. Drop old deal columns and other_description from posts
    op.drop_column('posts', 'grain_type_size')
    op.drop_column('posts', 'commodity_quantity_min')
    op.drop_column('posts', 'commodity_quantity_max')
    op.drop_column('posts', 'price_type')
    op.execute("ALTER TABLE posts DROP COLUMN IF EXISTS other_description")

    # 4. Remove 'Other' category (id=5) — delete dependent posts first
    op.execute("DELETE FROM posts WHERE category_id = 5")
    op.execute("DELETE FROM post_categories WHERE id = 5")

    # 5. Drop other_count from user_taste_profiles (category 5 removed)
    op.execute("ALTER TABLE user_taste_profiles DROP COLUMN IF EXISTS other_count")

    # 6. Truncate post_embeddings and resize vector column 11D → 10D
    op.execute("TRUNCATE TABLE post_embeddings")
    op.execute("ALTER TABLE post_embeddings ALTER COLUMN vector TYPE vector(10)")


def downgrade() -> None:
    # Restore deal columns and other_description on posts
    op.add_column('posts', sa.Column('grain_type_size', sa.String(100), nullable=True))
    op.add_column('posts', sa.Column('commodity_quantity_min', sa.Float(), nullable=True))
    op.add_column('posts', sa.Column('commodity_quantity_max', sa.Float(), nullable=True))
    op.add_column('posts', sa.Column('price_type', sa.String(20), nullable=True))
    op.add_column('posts', sa.Column('other_description', sa.Text(), nullable=True))

    # Remove title from posts
    op.drop_column('posts', 'title')

    # Restore 'Other' category
    op.execute("INSERT INTO post_categories (id, name) VALUES (5, 'Other')")

    # Drop post_deal_details table
    op.drop_table('post_deal_details')

    # Restore vector column to 11D (rows not restored)
    op.execute("ALTER TABLE post_embeddings ALTER COLUMN vector TYPE vector(11)")
