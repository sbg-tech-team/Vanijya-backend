"""notification_preferences — per-user push switches

Revision ID: e7d4a19c8b52
Revises: c4b81d5e9f30
Create Date: 2026-09-22

The Settings screen had three toggles writing to SharedPreferences with
nothing on the server reading them, so switching one off changed nothing.

No backfill: an absent row means every category is on, which is the existing
behaviour for every user who never opens Settings.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e7d4a19c8b52"
down_revision = "c4b81d5e9f30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_preferences",
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("push_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("market_alerts_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("group_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("notification_preferences", if_exists=True)
