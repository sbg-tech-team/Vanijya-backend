"""
SQLAlchemy model for user_global_taste.

Data layer — the only file in the taste module that imports SQLAlchemy.

user_global_taste stores the persistent cross-platform taste for each user.
Currently active dimension: commodity.
Placeholders will be populated as location and quantity modules are built.

Migration: run `alembic revision --autogenerate` and `alembic upgrade head`
after this model is registered in the alembic env.py Base metadata.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database.base import Base


class UserGlobalTaste(Base):
    """
    One row = one (user, dimension_type, dimension_key) triple.

    Composite unique constraint ensures exactly one row per user per dimension key.
    Rows are created lazily on first promotion; never pre-populated.
    """
    __tablename__ = "user_global_taste"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    profile_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True
    )
    dimension_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )                                          # "commodity" | "location" | "quantity"
    dimension_key: Mapped[str] = mapped_column(
        String(100), nullable=False
    )                                          # e.g. "42" (commodity_id as string)

    positive_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    negative_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    event_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    last_event_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "profile_id", "dimension_type", "dimension_key",
            name="uq_user_global_taste_profile_dim",
        ),
        Index(
            "ix_user_global_taste_profile_dim",
            "profile_id", "dimension_type",
        ),
    )
