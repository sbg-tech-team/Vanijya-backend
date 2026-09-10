from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database.base import Base


class VerificationRecord(Base):
    __tablename__ = "verification_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("profile.id", ondelete="CASCADE"))

    # "pan" | "aadhaar" | "gst" | "iec"
    document_type: Mapped[str] = mapped_column(String(10))
    document_number: Mapped[str] = mapped_column(String(100))

    # "kyc" (pan/aadhaar) | "kyb" (gst/iec)
    verification_category: Mapped[str] = mapped_column(String(5))

    # "verified" | "rejected" | "error"
    status: Mapped[str] = mapped_column(String(20))

    # which external API was called
    api_provider: Mapped[str] = mapped_column(String(50))

    # full response payload for audit
    api_response: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    error_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        # one active record per document type per user
        UniqueConstraint("profile_id", "document_type", name="uq_profile_document_type"),
    )
