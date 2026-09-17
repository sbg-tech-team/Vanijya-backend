from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional
from uuid import UUID

from app.modules.translation.domain.entities import ContextSnapshot


class IContextStore(ABC):
    """Rolling per-conversation summary used for disambiguation. Shared across
    every participant/device in a conversation — content, not a reader
    preference. get_context() also advances the due-for-refresh bookkeeping
    (call it once per translate request, not speculatively)."""

    @abstractmethod
    def get_context(self, context_type: str, context_id: UUID) -> ContextSnapshot:
        ...

    @abstractmethod
    def save_summary(
        self,
        context_type: str,
        context_id: UUID,
        summary: str,
        last_message_id: Optional[UUID],
    ) -> None:
        ...
