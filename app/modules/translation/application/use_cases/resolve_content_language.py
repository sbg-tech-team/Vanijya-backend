from __future__ import annotations

from typing import Optional
from uuid import UUID

from app.modules.translation.domain.exceptions import LanguageNotChosenError
from app.modules.translation.domain.interfaces.repository import ITranslationRepository
from app.modules.translation.domain.prompt import normalize_language


class ResolveContentLanguageUseCase:
    """Priority chain for post / comment / news translation:

        explicit target in the request
        > app language, when the reader runs the app in something other than English
        > reader's saved translation preference (reader_translation_defaults,
          the same app-wide default chat falls back to)
        > nothing: LanguageNotChosenError, and the client asks the reader.

    Deliberately no guess at the end, unlike chat's AUTO_FALLBACK — content is
    translated into a language the reader chose or none at all.
    """

    def __init__(self, repository: ITranslationRepository):
        self.repository = repository

    def execute(
        self,
        user_id: UUID,
        explicit_target_lang: Optional[str],
        app_language: Optional[str],
    ) -> str:
        explicit = normalize_language(explicit_target_lang)
        if explicit:
            return explicit

        app_lang = normalize_language(app_language)
        if app_lang and app_lang != "en":
            return app_lang

        preferred = normalize_language(self.repository.get_default_target_lang(user_id))
        if preferred:
            return preferred

        raise LanguageNotChosenError("Choose a language to translate into.")
