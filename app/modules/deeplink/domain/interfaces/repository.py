from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from app.modules.deeplink.domain.entities import ShareArticle, SharePost, ShareProfile


class IDeepLinkRepository(ABC):
    """Every database access in the deeplink module goes through this interface."""

    @abstractmethod
    def get_post(self, post_id: int) -> SharePost | None: ...

    @abstractmethod
    def get_article(self, article_id: UUID) -> ShareArticle | None: ...

    @abstractmethod
    def get_profile(self, profile_id: int) -> ShareProfile | None: ...
