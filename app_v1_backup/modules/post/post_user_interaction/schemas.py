from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator, model_validator

from app.modules.post.post_user_interaction.constants import VALID_CLIENT_EVENT_TYPES

_BATCH_MAX = 200


class InteractionEventItem(BaseModel):
    post_id: int
    event_type: str
    value_ms: Optional[int] = None
    occurred_at: datetime

    @field_validator("event_type")
    @classmethod
    def valid_event_type(cls, v: str) -> str:
        if v not in VALID_CLIENT_EVENT_TYPES:
            raise ValueError(
                f"Unknown event_type '{v}'. "
                f"Valid: {sorted(VALID_CLIENT_EVENT_TYPES)}"
            )
        return v

    @model_validator(mode="after")
    def dwell_requires_value_ms(self) -> "InteractionEventItem":
        if self.event_type == "dwell" and self.value_ms is None:
            raise ValueError("value_ms is required for dwell events")
        return self


class InteractionBatchPayload(BaseModel):
    events: list[InteractionEventItem]

    @field_validator("events")
    @classmethod
    def not_empty_and_bounded(cls, v: list) -> list:
        if not v:
            raise ValueError("events must not be empty")
        if len(v) > _BATCH_MAX:
            raise ValueError(f"Batch too large (max {_BATCH_MAX} events)")
        return v


class InteractionBatchResult(BaseModel):
    accepted: int
    dropped: int
