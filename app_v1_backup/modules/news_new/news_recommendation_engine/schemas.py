from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ArticleRecommendationScoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    profile_id: int
    article_id: UUID
    role_score: float
    profile_score: float | None = None
    taste_score: float | None = None
    final_score: float
    computed_at: datetime
    model_version: str | None = None
    is_served: bool


class FeedRankingCacheOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    profile_id: int
    feed_type: str
    ranked_article_ids: list | None = None
    computed_at: datetime
    expires_at: datetime
