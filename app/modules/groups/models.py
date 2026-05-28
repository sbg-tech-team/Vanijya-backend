import uuid
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.core.database.base import Base


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    group_rules: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Group image stored in the group-image Supabase bucket
    image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # JSONB arrays — e.g. ["sugar", "rice"]
    commodity: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    # JSONB array — e.g. ["trader", "broker"]
    target_roles: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    region_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    region_lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    region_market: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # commodity_trading | news | network
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # public | private | invite_only
    accessibility: Mapped[str] = mapped_column(String(20), default="public")
    # all_members | admins_only
    posting_perm: Mapped[str] = mapped_column(String(20), default="all_members")
    chat_perm: Mapped[str] = mapped_column(String(20), default="all_members")

    invite_link_token: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, unique=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    member_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    members: Mapped[List["GroupMember"]] = relationship(
        "GroupMember", back_populates="group", cascade="all, delete-orphan"
    )
    activity_cache: Mapped[Optional["GroupActivityCache"]] = relationship(
        "GroupActivityCache", back_populates="group", uselist=False,
        cascade="all, delete-orphan",
    )
    embedding: Mapped[Optional["GroupEmbedding"]] = relationship(
        "GroupEmbedding", back_populates="group", uselist=False,
        cascade="all, delete-orphan",
    )
    media: Mapped[List["GroupMedia"]] = relationship(
        "GroupMedia", back_populates="group", cascade="all, delete-orphan"
    )


class GroupMember(Base):
    __tablename__ = "group_members"

    group_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("groups.id"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # admin | member
    role: Mapped[str] = mapped_column(String(20), default="member")
    is_frozen: Mapped[bool] = mapped_column(Boolean, default=False)
    is_muted: Mapped[bool] = mapped_column(Boolean, default=False)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    group: Mapped["Group"] = relationship("Group", back_populates="members")


class GroupActivityCache(Base):
    __tablename__ = "group_activity_cache"

    group_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("groups.id"), primary_key=True
    )
    messages_24h: Mapped[int] = mapped_column(Integer, default=0)
    unique_senders_24h: Mapped[int] = mapped_column(Integer, default=0)
    active_members_7d: Mapped[int] = mapped_column(Integer, default=0)
    member_growth_7d: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    group: Mapped["Group"] = relationship("Group", back_populates="activity_cache")


class GroupEmbedding(Base):
    """11-dim pgvector IS vector. HNSW index for cosine ANN search."""
    __tablename__ = "group_embeddings"

    group_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("groups.id"), primary_key=True
    )
    # Layout: [3 commodity | 3 role | 3 geo | 2 zeros]
    embedding: Mapped[Optional[list]] = mapped_column(Vector(11), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    group: Mapped["Group"] = relationship("Group", back_populates="embedding")


class GroupMedia(Base):
    """
    Media files uploaded to a group — stored in the group-media Supabase bucket.
    Supported types: image (JPEG/PNG/WebP) and video (MP4/MOV/WebM).
    """
    __tablename__ = "group_media"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    media_url: Mapped[str] = mapped_column(String(500))
    # image | video
    media_type: Mapped[str] = mapped_column(String(20), default="image")
    storage_path: Mapped[str] = mapped_column(String(500))
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    group: Mapped["Group"] = relationship("Group", back_populates="media")


class GroupJoinRequest(Base):
    """Pending join requests for private groups — admin must approve or reject."""
    __tablename__ = "group_join_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # pending | approved | rejected
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    resolved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
