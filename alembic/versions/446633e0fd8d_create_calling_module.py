"""create calling module tables

Revision ID: 446633e0fd8d
Revises: d1e2f3a4b5c6
Create Date: 2026-09-15

New tables
----------
calls              – one row per call, 1:1 or group. `context_id` is polymorphic
                     by `call_type` (conversations.id for "dm", groups.id for
                     "group") and deliberately carries NO foreign key, so call
                     history survives deletion of the group or conversation.
call_participants  – one row per user per call, created at ring time so a missed
                     call still reports who was rung.
user_devices       – one push target per device, replacing the single
                     users.fcm_token column so every device rings. Seeded from
                     that column on upgrade.

Indexes are created up front: the ring-timeout sweeper and stale-call reaper both
scan calls by (status, created_at) / (status, started_at) on a schedule, and
GET /calls drives off call_participants.user_id.

Also extends messages.message_type usage with "call" — no schema change needed,
the column is already String(20) and unconstrained.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "446633e0fd8d"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stream_call_type", sa.String(length=30), nullable=False, server_default="default"),
        sa.Column("stream_call_id", sa.String(length=64), nullable=False),
        sa.Column("call_type", sa.String(length=10), nullable=False),
        sa.Column("media", sa.String(length=10), nullable=False, server_default="audio"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ringing"),
        sa.Column("context_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("initiator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("end_reason", sa.String(length=20), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stream_call_id", name="uq_calls_stream_call_id"),
        sa.ForeignKeyConstraint(["initiator_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_calls_status_created", "calls", ["status", "created_at"])
    op.create_index("ix_calls_initiator", "calls", ["initiator_id"])
    op.create_index("ix_calls_context", "calls", ["call_type", "context_id"])
    op.create_index("ix_calls_status_started", "calls", ["status", "started_at"])
    op.create_index("ix_calls_provider_ended", "calls", ["status", "provider_ended_at"])

    op.create_table(
        "call_participants",
        sa.Column("call_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False, server_default="callee"),
        sa.Column("state", sa.String(length=10), nullable=False, server_default="ringing"),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("call_id", "user_id"),
        sa.ForeignKeyConstraint(["call_id"], ["calls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_call_participants_user", "call_participants", ["user_id"])
    op.create_index("ix_call_participants_call_state", "call_participants", ["call_id", "state"])
    op.create_index("ix_call_participants_heartbeat", "call_participants", ["call_id", "last_heartbeat_at"])


    op.create_table(
        "user_devices",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fcm_token", sa.String(length=500), nullable=False),
        sa.Column("platform", sa.String(length=10), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fcm_token", name="uq_user_devices_fcm_token"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_user_devices_user", "user_devices", ["user_id"])

    # Seed from the single-token column so existing users keep ringing after the
    # switch — without this every already-registered device goes silent.
    op.execute(
        """
        INSERT INTO user_devices (id, user_id, fcm_token, last_seen_at, created_at)
        SELECT gen_random_uuid(), id, fcm_token, now(), now()
        FROM users
        WHERE fcm_token IS NOT NULL AND fcm_token <> ''
        ON CONFLICT (fcm_token) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_user_devices_user", table_name="user_devices")
    op.drop_table("user_devices")

    op.drop_index("ix_call_participants_heartbeat", table_name="call_participants")
    op.drop_index("ix_call_participants_call_state", table_name="call_participants")
    op.drop_index("ix_call_participants_user", table_name="call_participants")
    op.drop_table("call_participants")

    op.drop_index("ix_calls_provider_ended", table_name="calls")
    op.drop_index("ix_calls_status_started", table_name="calls")
    op.drop_index("ix_calls_context", table_name="calls")
    op.drop_index("ix_calls_initiator", table_name="calls")
    op.drop_index("ix_calls_status_created", table_name="calls")
    op.drop_table("calls")
