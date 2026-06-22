from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.news_new.config import (
    GEO_CATEGORIES,
    IMPACT_DIRECTIONS,
    PRIMARY_FACTORS,
)


class FactorScore(BaseModel):
    factor: str
    score: float


class ImpactPayload(BaseModel):
    direction: str
    score: float = Field(ge=0, le=10)
    factor: str | None = None
    explanation: str | None = None

    @field_validator("direction")
    @classmethod
    def _direction(cls, v: str) -> str:
        if v not in IMPACT_DIRECTIONS:
            raise ValueError(f"bad impact.direction: {v!r}")
        return v


class LLMEnrichment(BaseModel):
    """Validates the raw LLM output. Enums enforced here (post-call, retry once)."""
    primary_factor: str
    factor_scores: list[FactorScore] = []
    geo_category: str
    summary_bullets: list[str] = []
    impact: ImpactPayload

    @field_validator("primary_factor")
    @classmethod
    def _primary_factor(cls, v: str) -> str:
        if v not in PRIMARY_FACTORS:
            raise ValueError(f"bad primary_factor: {v!r}")
        return v

    @field_validator("geo_category")
    @classmethod
    def _geo(cls, v: str) -> str:
        if v not in GEO_CATEGORIES:
            raise ValueError(f"bad geo_category: {v!r}")
        return v


class EnrichedArticleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    raw_article_id: UUID
    primary_factor: str
    factor_scores: list | None = None
    geo_category: str
    summary_bullets: list | None = None
    impact_direction: str
    impact_score: float
    impact_factor: str | None = None
    impact_explanation: str | None = None
    role_trader: float
    role_broker: float
    role_exporter: float
    model_version: str | None = None
    generated_at: datetime
