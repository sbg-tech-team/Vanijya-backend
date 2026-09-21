from __future__ import annotations

from typing import Optional
from uuid import UUID

from app.modules.translation.application.use_cases.resolve_target_language import ResolveTargetLanguageUseCase
from app.modules.translation.domain.entities import ReaderConversationPrefs
from app.modules.translation.domain.exceptions import ContinuousNotAllowedError
from app.modules.translation.domain.interfaces.repository import ITranslationRepository
from app.modules.translation.domain.value_objects import AUTO_FALLBACK


class ToggleContinuousTranslationUseCase:
    """Turning continuous on resolves target_lang once, through the same chain
    single-tap uses, and stores the concrete result — incoming messages then
    just reuse that stored value. If nothing resolves anywhere (AUTO_FALLBACK),
    None is stored instead: that case is inherently per-message (depends on
    each incoming message's own source language), so it can't be snapshotted —
    HandleIncomingMessageUseCase re-enters AUTO_FALLBACK on every message until
    the reader sets something concrete."""

    def __init__(self, repository: ITranslationRepository, resolve_target_language: ResolveTargetLanguageUseCase):
        self.repository = repository
        self.resolve_target_language = resolve_target_language

    def get_state(self, user_id: UUID, conversation_id: UUID) -> ReaderConversationPrefs:
        """Current setting, so a client that restarted does not show "off"
        while the server is still translating. Keyed by user_id, so this can
        only ever read the caller's own preference."""
        pref = self.repository.get_conversation_pref(user_id, conversation_id)
        if pref is None:
            return ReaderConversationPrefs(
                user_id=user_id,
                conversation_id=conversation_id,
                target_lang=None,
                continuous_enabled=False,
            )
        return pref

    def execute(
        self,
        user_id: UUID,
        conversation_id: UUID,
        context_type: str,
        enabled: bool,
        explicit_target_lang: Optional[str] = None,
    ) -> ReaderConversationPrefs:
        if context_type != "dm":
            raise ContinuousNotAllowedError("Continuous translation is only available for direct messages.")

        target_to_store = None
        if enabled:
            resolved = self.resolve_target_language.execute(user_id, conversation_id, explicit_target_lang)
            target_to_store = None if resolved == AUTO_FALLBACK else resolved

        return self.repository.set_conversation_pref(
            user_id, conversation_id, target_lang=target_to_store, continuous_enabled=enabled
        )
