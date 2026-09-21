"""user_devices.token_type — tell FCM tokens from iOS PushKit VoIP tokens

Revision ID: c4b81d5e9f30
Revises: a1f7c93b204e
Create Date: 2026-09-21

An iOS client has two push tokens and both were arriving at POST /calls/devices
as `platform: "ios"` with nothing to distinguish them. A PushKit token is a raw
APNs device token, which Firebase cannot deliver to, so storing one as an FCM
token means that device silently never rings.
"""
from alembic import op
import sqlalchemy as sa

revision = "c4b81d5e9f30"
down_revision = "a1f7c93b204e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_devices",
        sa.Column("token_type", sa.String(10), nullable=False, server_default="fcm"),
    )


def downgrade() -> None:
    op.drop_column("user_devices", "token_type")
