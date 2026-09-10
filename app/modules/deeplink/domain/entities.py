"""Pure share-target shapes. No SQLAlchemy, no FastAPI, no Pydantic."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SharePost:
    post_id: int
    caption: str | None
    image_url: str | None
    author_name: str | None      # None -> use the "Vanijyaa User" fallback


@dataclass(frozen=True)
class ShareArticle:
    title: str
    summary: str | None
    image_url: str | None


@dataclass(frozen=True)
class ShareProfile:
    profile_id: int
    name: str
    avatar_url: str | None
    business_name: str | None
    city: str | None
