import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database.base import Base


class Call(Base):
    """One call, 1:1 or group.

    `context_id` is polymorphic by `call_type`: a conversations.id for "dm",
    a groups.id for "group". No hard FK — a call record outlives the group or
    conversation it belonged to, so history never breaks on deletion.
    """

    __tablename__ = "calls"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # How Stream addresses this call. Stored so a token can be re-minted for a
    # call in progress without recomputing the id.
    stream_call_type: Mapped[str] = mapped_column(String(30), nullable=False, default="default")
    stream_call_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    call_type: Mapped[str] = mapped_column(String(10), nullable=False)     # dm | group
    media: Mapped[str] = mapped_column(String(10), nullable=False, default="audio")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ringing")

    context_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)

    initiator_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    # Set once, on the first accept. Never moved by later joins — duration is
    # measured from here.
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # When the provider session was confirmed terminated. NULL on a terminal
    # call means mark_ended never succeeded — the media session may still be
    # billing, so a sweeper retries it.
    provider_ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_reason: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    participants: Mapped[list["CallParticipant"]] = relationship(
        "CallParticipant", back_populates="call", cascade="all, delete-orphan",
    )

    __table_args__ = (
        # Ring-timeout sweeper and stale-call reaper both scan (status, created_at).
        Index("ix_calls_status_created", "status", "created_at"),
        Index("ix_calls_initiator", "initiator_id"),
        Index("ix_calls_context", "call_type", "context_id"),
        Index("ix_calls_status_started", "status", "started_at"),
        # Drives the provider-termination retry sweep.
        Index("ix_calls_provider_ended", "status", "provider_ended_at"),
    )


class CallParticipant(Base):
    """One user's involvement in one call.

    Row exists from the moment the call is created (state="ringing"), so a
    missed call still has a participant row to report in history.
    """

    __tablename__ = "call_participants"

    call_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )

    role: Mapped[str] = mapped_column(String(10), nullable=False, default="callee")
    state: Mapped[str] = mapped_column(String(10), nullable=False, default="ringing")

    joined_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    left_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Liveness, per participant rather than per call. Presence is a property of
    # a person, not of a conversation: a call-level heartbeat cannot tell
    # "both still talking" from "one person alone while the other's app died",
    # because whoever is still alive keeps the call-level timestamp fresh.
    # It also means a caller whose app dies before ever joining the media
    # session stops counting as present, which a `state` column alone cannot
    # express — we mark the caller joined optimistically at ring time.
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    call: Mapped["Call"] = relationship("Call", back_populates="participants")

    __table_args__ = (
        # History is "every call I was part of, newest first" — this is the
        # driving index for GET /calls.
        Index("ix_call_participants_user", "user_id"),
        Index("ix_call_participants_call_state", "call_id", "state"),
        Index("ix_call_participants_heartbeat", "call_id", "last_heartbeat_at"),
    )


class UserDevice(Base):
    """One push target per device.

    `users.fcm_token` holds a single token, so only the most recently registered
    device could ever ring — a user with a phone and a tablet would miss calls on
    whichever they registered first. This table replaces that for calling; the
    old column is still written for backward compatibility with anything else
    that reads it.

    Behaviour chosen: ring EVERY device, first answer wins, the rest are told to
    stop. That is what WhatsApp and Telegram do and what users expect.
    """

    __tablename__ = "user_devices"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Unique so re-registering the same token moves it to the current user
    # rather than ringing the previous owner's phone.
    fcm_token: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    platform: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # ios | android | web
    # fcm  – an FCM registration token, deliverable via firebase_admin.
    # voip – an iOS PushKit token: a raw APNs device token that FCM cannot
    #        send to. Stored so it is ready for the direct-APNs path, and
    #        skipped by the FCM fan-out until that exists.
    token_type: Mapped[str] = mapped_column(String(10), nullable=False, default="fcm")
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_user_devices_user", "user_id"),
    )
