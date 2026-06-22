from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class CursorMeta(BaseModel):
    next_cursor: str | None = None
    has_more: bool


class NewsCard(BaseModel):
    article_id: UUID
    title: str
    image_url: str | None = None
    source_name: str | None = None
    time_on_platform: str
    platform_arrived_at: datetime
    summary_bullets: list[str] | None = None
    primary_factor: str | None = None
    geo_category: str | None = None
    impact_direction: str | None = None
    impact_score: float | None = None
    like_count: int = 0
    share_count: int = 0
    is_liked: bool = False
    is_saved: bool = False
    role_score: float | None = None
    final_score: float | None = None


class NewsCardDetail(NewsCard):
    description: str | None = None
    article_url: str
    source_url: str | None = None
    published_at: datetime
    impact_explanation: str | None = None
    impact_factor: str | None = None
    factor_scores: list | None = None
    view_count: int | None = None
    save_count: int | None = None


class FeedPage(BaseModel):
    items: list[NewsCard]
    cursor: CursorMeta
