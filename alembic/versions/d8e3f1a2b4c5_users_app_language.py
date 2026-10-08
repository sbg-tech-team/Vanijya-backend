"""users.app_language — the language the user runs the app in

Revision ID: d8e3f1a2b4c5
Revises: c7d2e9f4a1b3
Create Date: 2026-10-07

Chosen at onboarding (PUT /auth/app-language), en | hi for now. NOT NULL
with server default 'en', so every existing user reads as English without a
backfill and the column add does not rewrite the table on Postgres 11+.
"""
from alembic import op
import sqlalchemy as sa

revision = "d8e3f1a2b4c5"
down_revision = "c7d2e9f4a1b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("app_language", sa.String(10), nullable=False, server_default="en"),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_column("users", "app_language", if_exists=True)
