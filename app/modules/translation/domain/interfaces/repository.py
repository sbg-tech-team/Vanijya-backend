from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional
from uuid import UUID

from app.modules.translation.domain.entities import (
    ContextMessage,
    ReaderConversationPrefs,
    TranslatableMessage,
)


class ITranslationRepository(ABC):
    """Postgres-only access this module needs: reading chat's own message
    history (read-only — chat remains the owner of that table) and reading/
    writing this module's reader-preference tables."""

    # ── message history (read-only view into chat's messages table) ──────────
    @abstractmethod
    def get_message(self, message_id: UUID) -> Optional[TranslatableMessage]:
        ...

    @abstractmethod
    def get_preceding_messages(
        self, context_type: str, context_id: UUID, before_message_id: UUID, limit: int
    ) -> list[ContextMessage]:
        ...

    # ── reader preferences ────────────────────────────────────────────────────
    @abstractmethod
    def get_conversation_pref(self, user_id: UUID, conversation_id: UUID) -> Optional[ReaderConversationPrefs]:
        ...

    @abstractmethod
    def get_default_target_lang(self, user_id: UUID) -> Optional[str]:
        ...

    @abstractmethod
    def set_conversation_pref(
        self,
        user_id: UUID,
        conversation_id: UUID,
        target_lang: Optional[str] = None,
        continuous_enabled: Optional[bool] = None,
    ) -> ReaderConversationPrefs:
        ...

    @abstractmethod
    def set_default_target_lang(self, user_id: UUID, target_lang: str) -> None:
        ...
