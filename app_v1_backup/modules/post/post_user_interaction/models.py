from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database.base import Base


class PostInteractionEvent(Base):
    """
    Append-only log of every post interaction signal.
    Written by the batch endpoint (client events) and by _record_view()
    (server-generated revisit events).
    """
    __tablename__ = "post_interaction_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("profile.id", ondelete="CASCADE"), nullable=False
    )
    post_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False
    )
    # impression | dwell | open_read_more | open_carousel | open_comments
    # | link_click | revisit
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    value_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)   # dwell only
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    # NULL = not yet processed by run_taste_update_job; set to now when job runs
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    __table_args__ = (
        Index("ix_pie_profile_post", "profile_id", "post_id"),
        Index("ix_pie_event_type_created", "event_type", "created_at"),
        Index("ix_pie_created_at", "created_at"),
        # Partial-style index for the async job: dwell events not yet processed
        Index("ix_pie_event_type_processed", "event_type", "processed_at"),
    )


class UserPostTaste(Base):
    """
    Row-per-dimension persistent taste store.

    Each row represents a user's accumulated taste signal for one dimension:
      dimension_type='category'  dimension_key='market_update'
      dimension_type='commodity' dimension_key='1'   (commodity_id as str)
      dimension_type='author'    dimension_key='42'  (author profile_id as str, Phase 5A)

    Composite PK = (profile_id, dimension_type, dimension_key).
    Scores are Float to hold fractional signal weights.
    Replaces UserTasteProfile as the active read path in Phase 7.
    """
    __tablename__ = "user_post_taste"

    profile_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("profile.id", ondelete="CASCADE"),
        primary_key=True, nullable=False
    )
    dimension_type: Mapped[str] = mapped_column(
        String(20), primary_key=True, nullable=False
    )
    dimension_key: Mapped[str] = mapped_column(
        String(50), primary_key=True, nullable=False
    )
    positive_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    negative_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_event_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        Index("ix_upt_profile_type", "profile_id", "dimension_type"),
    )


class UserTasteProfile(Base):
    """
    Legacy flat-counter taste store (Phase 1 / Phase 2).
    Still the active read path for the reranker until Phase 7 cutover.
    Superseded by UserPostTaste — do not add columns here.
    """
    __tablename__ = "user_taste_profiles"

    profile_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("profile.id", ondelete="CASCADE"), primary_key=True
    )
    market_update_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deal_req_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    discussion_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    knowledge_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
