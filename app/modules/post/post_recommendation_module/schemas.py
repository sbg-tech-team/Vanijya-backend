from typing import List
from pydantic import BaseModel, field_validator

from app.modules.post.schemas import FeedPostCard  # noqa: F401 — re-exported for callers


class FeedResponse(BaseModel):
    posts: List[FeedPostCard]
    has_more: bool


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
