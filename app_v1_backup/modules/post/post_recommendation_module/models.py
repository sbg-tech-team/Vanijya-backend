from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.core.database.base import Base

# UserTasteProfile has moved to app.modules.post.post_user_interaction.models


class PostEmbedding(Base):
    __tablename__ = "post_embeddings"

    post_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True
    )
    vector: Mapped[list] = mapped_column(Vector(10), nullable=False)
    partition: Mapped[str] = mapped_column(String(10), nullable=False, default="hot")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    commodity_idx: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=cotton 1=rice 2=sugar
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class PopularPost(Base):
    __tablename__ = "popular_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("posts.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    commodity_idx: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    velocity_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    saves_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    likes_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    comments_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hours_since_post: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SeenPost(Base):
    __tablename__ = "seen_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("profile.id", ondelete="CASCADE"), nullable=False
    )
    post_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False
    )
    seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("profile_id", "post_id", name="uq_seen_post"),
    )
