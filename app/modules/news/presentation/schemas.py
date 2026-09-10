"""
Pydantic schemas for the news module API.

Request schemas validate inbound data.
Response schemas shape outbound JSON — must match app_v1_backup byte-for-byte
(field names, not just types), since the live mobile client is built against
that shape.
No SQLAlchemy or domain entities cross into this file.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.modules.news.domain.value_objects import CLIENT_EVENT_TYPES

_BATCH_MAX = 200


# ── Request schemas ────────────────────────────────────────────────────────────

class RecordEventItem(BaseModel):
    article_id: UUID
    event_type: str
    occurred_at: datetime
    value_ms: Optional[int] = None

    @field_validator("event_type")
    @classmethod
    def valid_event_type(cls, v: str) -> str:
        if v not in CLIENT_EVENT_TYPES:
            raise ValueError(
                f"Unknown event_type '{v}'. Valid: {sorted(CLIENT_EVENT_TYPES)}"
            )
        return v

    @model_validator(mode="after")
    def dwell_requires_value_ms(self) -> "RecordEventItem":
        if self.event_type == "dwell" and self.value_ms is None:
            raise ValueError("value_ms is required for dwell events")
        return self


class RecordEventsRequest(BaseModel):
    events: list[RecordEventItem]

    @field_validator("events")
    @classmethod
    def not_empty_and_bounded(cls, v: list) -> list:
        if not v:
            raise ValueError("events must not be empty")
        if len(v) > _BATCH_MAX:
            raise ValueError(f"Batch too large (max {_BATCH_MAX} events)")
        return v


class SendArticleRequest(BaseModel):
    dm_conversation_ids: list[UUID] = Field(default_factory=list)
    group_ids: list[UUID] = Field(default_factory=list)
    caption: Optional[str] = Field(None, max_length=4000)

    @model_validator(mode="after")
    def at_least_one_recipient(self) -> "SendArticleRequest":
        if not self.dm_conversation_ids and not self.group_ids:
            raise ValueError("Provide at least one DM conversation or group to share to.")
        return self


# ── Response schemas ───────────────────────────────────────────────────────────

class NewsCardOut(BaseModel):
    article_id: UUID
    title: str
    platform_arrived_at: datetime
    time_on_platform: str
    image_url: Optional[str] = None
    source_name: Optional[str] = None
    summary_bullets: Optional[list[str]] = None
    primary_factor: Optional[str] = None
    geo_category: Optional[str] = None
    is_government: bool = False
    impact_direction: Optional[str] = None
    impact_score: Optional[float] = None
    like_count: int = 0
    share_count: int = 0
    is_liked: bool = False
    is_saved: bool = False

    model_config = {"from_attributes": True}


class NewsCardDetailOut(NewsCardOut):
    description: Optional[str] = None
    article_url: str = ""
    source_url: Optional[str] = None
    published_at: Optional[datetime] = None
    impact_explanation: Optional[str] = None
    impact_factor: Optional[str] = None
    factor_scores: Optional[list] = None
    view_count: Optional[int] = None
    save_count: Optional[int] = None


class NewsFeedPageOut(BaseModel):
    articles: list[NewsCardOut]
    next_cursor: Optional[str] = None


class ToggleLikeOut(BaseModel):
    article_id: UUID
    is_liked: bool


class ToggleSaveOut(BaseModel):
    article_id: UUID
    is_saved: bool


class NewsShareOut(BaseModel):
    article_id: UUID
    platform: Optional[str] = None


class RecordEventsOut(BaseModel):
    accepted: int
    dropped: int


class NewsSendResponse(BaseModel):
    share_count: int
    delivered_to: int


class IngestionStatsOut(BaseModel):
    pending: int = 0
    processing: int = 0
    enriched: int = 0
    failed: int = 0


class IngestResultOut(BaseModel):
    provider: str
    queries_run: int
    saved: int
    skipped: int
    errors: int


class EnrichResultOut(BaseModel):
    model: str
    processed: int
    enriched: int
    failed: int
