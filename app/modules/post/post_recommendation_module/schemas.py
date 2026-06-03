from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, field_validator

from app.modules.post.schemas import PostDealResponse


class FeedPostCard(BaseModel):
    # ── Post ──────────────────────────────────────────────────────────────────
    id: int
    profile_id: int
    category_id: int
    commodity_id: int
    title: str
    caption: str
    image_url: Optional[str] = None
    is_public: bool
    target_roles: Optional[List[int]] = None
    allow_comments: bool
    deal_details: Optional[PostDealResponse] = None
    source_url: Optional[str] = None
    location_name: Optional[str] = None   # pre-built: post.location_name OR "city, state"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    view_count: int
    like_count: int
    comment_count: int
    share_count: int
    save_count: int
    is_liked: bool
    is_saved: bool
    created_at: datetime

    # ── Author ────────────────────────────────────────────────────────────────
    author_name: str
    author_role: str                       # "trader" | "broker" | "exporter"
    author_user_id: str                    # UUID string — needed for Follow button
    author_company: Optional[str] = None
    author_avatar_url: Optional[str] = None
    is_user_verified: bool
    is_business_verified: bool

    # ── Comment preview ───────────────────────────────────────────────────────
    comment_preview_author: Optional[str] = None
    comment_preview_text: Optional[str] = None


class PostSeenPayload(BaseModel):
    """Post IDs the client considers seen. Frontend decides the threshold."""
    post_ids: List[int]

    @field_validator("post_ids")
    @classmethod
    def not_empty(cls, v: List[int]) -> List[int]:
        if not v:
            raise ValueError("post_ids must not be empty")
        return v


class JobResult(BaseModel):
    status: str
    details: dict
