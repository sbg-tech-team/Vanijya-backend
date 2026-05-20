"""create_verification_module

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-05-19

Replaces profile_documents with verification_records.
verification_records is richer: stores the full API response, provider name,
error detail, and timestamps so every KYC/KYB attempt is auditable.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'd0e1f2a3b4c5'
down_revision: Union[str, None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table('profile_documents')
    op.drop_column('profile', 'is_verified')

    op.create_table(
        'verification_records',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('profile_id', sa.Integer(), nullable=False),
        sa.Column('document_type', sa.String(10), nullable=False),
        sa.Column('document_number', sa.String(100), nullable=False),
        sa.Column('verification_category', sa.String(5), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('api_provider', sa.String(50), nullable=False),
        sa.Column('api_response', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.String(500), nullable=True),
        sa.Column('verified_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['profile_id'], ['profile.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('profile_id', 'document_type', name='uq_profile_document_type'),
    )


def downgrade() -> None:
    op.drop_table('verification_records')
    op.add_column('profile', sa.Column('is_verified', sa.Boolean(), nullable=False, server_default='false'))

    op.create_table(
        'profile_documents',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('profile_id', sa.Integer(), nullable=False),
        sa.Column('document_type', sa.String(30), nullable=False),
        sa.Column('document_number', sa.String(100), nullable=False),
        sa.Column('verification_status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('verified_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['profile_id'], ['profile.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
