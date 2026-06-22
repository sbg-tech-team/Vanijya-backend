from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator, model_validator

from app.modules.news_new.news_user_interaction.constants import VALID_CLIENT_EVENT_TYPES

_BATCH_MAX = 200


class NewsInteractionEventItem(BaseModel):
    article_id: UUID
    event_type: str
    value_ms: int | None = None
    occurred_at: datetime

    @field_validator("event_type")
    @classmethod
    def valid_event_type(cls, v: str) -> str:
        if v not in VALID_CLIENT_EVENT_TYPES:
            raise ValueError(
                f"Unknown event_type '{v}'. Valid: {sorted(VALID_CLIENT_EVENT_TYPES)}"
            )
        return v

    @model_validator(mode="after")
    def dwell_requires_value_ms(self) -> "NewsInteractionEventItem":
        if self.event_type == "dwell" and self.value_ms is None:
            raise ValueError("value_ms is required for dwell events")
        return self


class NewsInteractionBatchPayload(BaseModel):
    events: list[NewsInteractionEventItem]

    @field_validator("events")
    @classmethod
    def not_empty_and_bounded(cls, v: list) -> list:
        if not v:
            raise ValueError("events must not be empty")
        if len(v) > _BATCH_MAX:
            raise ValueError(f"Batch too large (max {_BATCH_MAX} events)")
        return v


class NewsInteractionBatchResult(BaseModel):
    accepted: int
    dropped: int


class NewsLikeOut(BaseModel):
    article_id: UUID
    is_liked: bool


class NewsSaveOut(BaseModel):
    article_id: UUID
    is_saved: bool


class NewsShareOut(BaseModel):
    article_id: UUID
    platform: str | None = None
