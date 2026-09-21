from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
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
    def reader_is_member(self, reader_id: UUID, context_type: str, context_id: UUID) -> bool:
        """Is this reader allowed to see messages in this DM/group at all?"""
        ...

    @abstractmethod
    def get_preceding_messages(
        self, context_type: str, context_id: UUID, before_message_id: UUID, limit: int
    ) -> list[ContextMessage]:
        ...

    @abstractmethod
    def save_translation(self, message_id: UUID, target_lang: str, translated_text: str) -> None:
        """Persist a finished translation so it survives scroll-back, thread
        reopen, socket reconnect and process restart."""
        ...

    @abstractmethod
    def untranslated_for_continuous_readers(
        self, since: datetime, limit: int
    ) -> list[tuple[UUID, UUID]]:
        """(receiver_id, message_id) pairs whose live translation never landed."""
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
