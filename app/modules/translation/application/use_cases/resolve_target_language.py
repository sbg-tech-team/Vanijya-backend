from __future__ import annotations

from typing import Optional
from uuid import UUID

from app.modules.translation.domain.interfaces.repository import ITranslationRepository
from app.modules.translation.domain.value_objects import AUTO_FALLBACK


class ResolveTargetLanguageUseCase:
    """Priority chain: explicit per-message override > per-reader conversation
    pref > reader's app-wide default > AUTO_FALLBACK sentinel."""

    def __init__(self, repository: ITranslationRepository):
        self.repository = repository

    def execute(
        self,
        reader_id: UUID,
        conversation_id: UUID,
        explicit_target_lang: Optional[str] = None,
    ) -> str:
        if explicit_target_lang:
            return explicit_target_lang

        conv_pref = self.repository.get_conversation_pref(reader_id, conversation_id)
        if conv_pref and conv_pref.target_lang:
            return conv_pref.target_lang

        default = self.repository.get_default_target_lang(reader_id)
        if default:
            return default

        return AUTO_FALLBACK
