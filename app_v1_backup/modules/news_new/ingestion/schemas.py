from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CanonicalArticle(BaseModel):
    """Adapter output — the one shape every provider must produce."""
    external_id: str
    title: str
    description: str | None = None
    content: str | None = None
    article_url: str
    image_url: str | None = None
    published_at: datetime
    language: str | None = None
    source_name: str | None = None
    source_url: str | None = None
    source_country: str | None = None
    authors: list[str] = []
    is_duplicate: bool = False
    api_summary: str | None = None
    raw_metadata: dict = {}


class RawArticleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    external_id: str
    title: str
    description: str | None = None
    article_url: str
    image_url: str | None = None
    published_at: datetime
    source_name: str | None = None
    source_country: str | None = None
    intelligence_status: str
    platform_arrived_at: datetime


class IngestResult(BaseModel):
    provider: str
    query: str
    fetched: int
    new: int
    skipped: int


class EnrichResult(BaseModel):
    enriched: int
    failed: int
    remaining_pending: int


class IngestionStats(BaseModel):
    total: int
    pending: int
    enriched: int
    failed: int
