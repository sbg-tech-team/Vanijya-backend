from __future__ import annotations

from typing import Optional
from uuid import UUID

from app.modules.translation.domain.interfaces.repository import ITranslationRepository
from app.modules.translation.domain.prompt import normalize_language


class TranslationPreferenceUseCase:
    """The reader's saved translation language — the one used when the app
    itself runs in English. Stored in reader_translation_defaults, the same
    row chat already falls back to, so one setting drives both."""

    def __init__(self, repository: ITranslationRepository):
        self.repository = repository

    def get(self, user_id: UUID) -> Optional[str]:
        return normalize_language(self.repository.get_default_target_lang(user_id))

    def set(self, user_id: UUID, target_lang: str) -> str:
        lang = normalize_language(target_lang)
        if lang is None:
            raise ValueError(f"unsupported language: {target_lang!r}")
        self.repository.set_default_target_lang(user_id, lang)
        return lang
