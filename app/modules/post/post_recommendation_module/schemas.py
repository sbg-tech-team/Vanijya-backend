from typing import Optional, List
from pydantic import BaseModel, field_validator

from app.modules.post.schemas import PostResponse


class PostAuthorResponse(BaseModel):
    profile_id: int
    name: str
    role_id: int
    avatar_url: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    is_user_verified: bool
    is_business_verified: bool

    class Config:
        from_attributes = True


class FeedPostCard(BaseModel):
    post: PostResponse
    author: PostAuthorResponse
    score: float


class PostSeenPayload(BaseModel):
    """Post IDs the client considers seen. Frontend decides the threshold (dwell, scroll, open)."""
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
