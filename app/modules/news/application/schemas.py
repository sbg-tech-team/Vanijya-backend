"""News response shapes owned by the application layer.

`NewsCardOut` is the news module's public card contract. Defined here so other
modules can depend on it without importing news' presentation layer. presentation/schemas.py re-exports it, so
the wire format and every existing import site are unchanged.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


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
