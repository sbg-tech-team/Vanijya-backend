from __future__ import annotations

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class OpenChatRequest(BaseModel):
    participant_id: UUID
    message: str = Field(..., min_length=1, max_length=4000)


class SendMessageRequest(BaseModel):
    body: Optional[str] = Field(None, max_length=4000)
    message_type: str = Field("text", pattern="^(text|image|video|document|audio|location|system|post|news|user|deal)$")
    media_url: Optional[str] = Field(None, max_length=500)
    media_metadata: Optional[dict] = None
    location_lat: Optional[float] = None
    location_lon: Optional[float] = None
    reply_to_id: Optional[UUID] = None


class GroupMessageRequest(BaseModel):
    body: Optional[str] = Field(None, max_length=4000)
    message_type: str = Field("text", pattern="^(text|image|video|document|audio|location|system|post|news|user|deal)$")
    media_url: Optional[str] = Field(None, max_length=500)
    media_metadata: Optional[dict] = None
    reply_to_id: Optional[UUID] = None
