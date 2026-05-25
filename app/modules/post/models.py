from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import ARRAY, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database.base import Base


# ---------------------------------------------------------------------------
# Fixed category IDs – seeded in migration
# ---------------------------------------------------------------------------
# 1 = Market Update
# 2 = Knowledge
# 3 = Discussion
# 4 = Deal / Requirement

CATEGORY_DEAL = 4


class PostCategory(Base):
    __tablename__ = "post_categories"

    # No autoincrement – IDs are fixed and seeded (1-4)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)

    posts: Mapped[list["Post"]] = relationship("Post", back_populates="post_category")


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("profile.id", ondelete="CASCADE"))
    category_id: Mapped[int] = mapped_column(Integer, ForeignKey("post_categories.id"))
    commodity_id: Mapped[int] = mapped_column(Integer, ForeignKey("commodities.id"))

    # Content
    title: Mapped[str] = mapped_column(String(200))
    image_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    caption: Mapped[str] = mapped_column(Text)

    # Visibility
    is_public: Mapped[bool] = mapped_column(default=True)
    target_roles: Mapped[Optional[list[int]]] = mapped_column(ARRAY(Integer), nullable=True)

    # Interaction controls
    allow_comments: Mapped[bool] = mapped_column(default=True)

    # Counters
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, default=0)
    share_count: Mapped[int] = mapped_column(Integer, default=0)
    save_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    post_category: Mapped["PostCategory"] = relationship("PostCategory", back_populates="posts")
    deal_details: Mapped[Optional["PostDealDetails"]] = relationship(
        "PostDealDetails", back_populates="post", uselist=False, cascade="all, delete-orphan"
    )
    views: Mapped[list["PostView"]] = relationship("PostView", back_populates="post", cascade="all, delete-orphan")
    likes: Mapped[list["PostLike"]] = relationship("PostLike", back_populates="post", cascade="all, delete-orphan")
    comments: Mapped[list["PostComment"]] = relationship("PostComment", back_populates="post", cascade="all, delete-orphan")
    shares: Mapped[list["PostShare"]] = relationship("PostShare", back_populates="post", cascade="all, delete-orphan")
    saves: Mapped[list["PostSave"]] = relationship("PostSave", back_populates="post", cascade="all, delete-orphan")


class PostDealDetails(Base):
    __tablename__ = "post_deal_details"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), unique=True)

    grain_type: Mapped[str] = mapped_column(String(100))
    grain_size: Mapped[str] = mapped_column(String(50))
    commodity_quantity: Mapped[float] = mapped_column(Float)
    quantity_unit: Mapped[str] = mapped_column(String(20))   # MT | quintal
    commodity_price: Mapped[float] = mapped_column(Float)
    price_type: Mapped[str] = mapped_column(String(20))      # fixed | negotiable
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)

    post: Mapped["Post"] = relationship("Post", back_populates="deal_details")


class PostView(Base):
    __tablename__ = "post_views"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(Integer, ForeignKey("posts.id", ondelete="CASCADE"))
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("profile.id", ondelete="CASCADE"))
    viewed_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("post_id", "profile_id", name="uq_post_view"),
    )

    post: Mapped["Post"] = relationship("Post", back_populates="views")


class PostLike(Base):
    __tablename__ = "post_likes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(Integer, ForeignKey("posts.id", ondelete="CASCADE"))
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("profile.id", ondelete="CASCADE"))
    liked_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("post_id", "profile_id", name="uq_post_like"),
    )

    post: Mapped["Post"] = relationship("Post", back_populates="likes")


class PostComment(Base):
    __tablename__ = "post_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(Integer, ForeignKey("posts.id", ondelete="CASCADE"))
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("profile.id", ondelete="CASCADE"))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    post: Mapped["Post"] = relationship("Post", back_populates="comments")


class PostShare(Base):
    __tablename__ = "post_shares"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(Integer, ForeignKey("posts.id", ondelete="CASCADE"))
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("profile.id", ondelete="CASCADE"))
    shared_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    post: Mapped["Post"] = relationship("Post", back_populates="shares")


class PostSave(Base):
    __tablename__ = "post_saves"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(Integer, ForeignKey("posts.id", ondelete="CASCADE"))
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("profile.id", ondelete="CASCADE"))
    saved_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("post_id", "profile_id", name="uq_post_save"),
    )

    post: Mapped["Post"] = relationship("Post", back_populates="saves")
