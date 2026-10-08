from __future__ import annotations

import logging
import unicodedata
from typing import Callable, Optional

from app.modules.translation.domain.exceptions import TranslationEngineUnavailableError
from app.modules.translation.domain.interfaces.content_engine import IContentTranslationEngine
from app.modules.translation.domain.interfaces.suggestion_cache import ISuggestionCache
from app.modules.translation.domain.names import MAX_NAME_LENGTH, script_language
from app.modules.translation.domain.prompt import LANGUAGE_NAMES, language_name
from app.modules.translation.domain.transliteration import normalize_spelling, sounds_the_same
from app.modules.translation.domain.transliteration_prompt import assemble_name_suggestions_prompt
from app.modules.translation.domain.value_objects import (
    NAME_SUGGESTIONS_CACHE_TTL_SECONDS,
    NAME_SUGGESTIONS_MAX,
)

log = logging.getLogger(__name__)


class NameSuggestionsUseCase:
    """Spellings of a name in another script, offered while the person types
    it (called once they stop typing). The person picks one or types their
    own — whatever they choose is stored as theirs (profile.name_i18n).

    Every English<->Hindi suggestion must pass the same sound check names are
    held to (a changed ending is never offered). Other script pairs are not
    screened yet beyond being in the right script; the person still decides.

    `before_engine_call` runs only when the engine is actually called — the
    caller rate-limits there, so cached answers are free.
    """

    def __init__(self, engine: IContentTranslationEngine, cache: ISuggestionCache):
        self.engine = engine
        self.cache = cache

    def execute(
        self,
        text: str,
        target_lang: str,
        before_engine_call: Optional[Callable[[], None]] = None,
    ) -> tuple[str, list[str]]:
        """(language the name was typed in, suggestions). Raises ValueError
        for unusable input."""
        text = " ".join(unicodedata.normalize("NFC", text or "").split())
        if not text or len(text) > MAX_NAME_LENGTH:
            raise ValueError(f"name must be 1-{MAX_NAME_LENGTH} characters")
        if target_lang not in LANGUAGE_NAMES:
            raise ValueError(f"unsupported language {target_lang!r}")
        source = script_language(text)
        if source is None:
            raise ValueError("name has no letters")
        if source == target_lang:
            return source, [text]

        key = f"{target_lang}:{text.lower()}"
        cached = self.cache.get(key)
        if cached is not None:
            return source, cached

        if not self.engine.is_configured:
            raise TranslationEngineUnavailableError("Translation engine is not configured")
        if before_engine_call is not None:
            before_engine_call()

        try:
            out = self.engine.translate_fields(
                assemble_name_suggestions_prompt(text, language_name(target_lang)))
        except Exception as exc:
            log.warning("name suggestions failed for %s -> %s: %s", source, target_lang, exc)
            return source, []

        raw = out.get("suggestions") if isinstance(out, dict) else None
        suggestions = self._screen(text, source, target_lang, raw if isinstance(raw, list) else [])
        if suggestions:
            self.cache.set(key, suggestions, NAME_SUGGESTIONS_CACHE_TTL_SECONDS)
        return source, suggestions

    @staticmethod
    def _screen(text: str, source: str, target: str, raw: list) -> list[str]:
        out: list[str] = []
        exact: list[str] = []      # sound the same under the strict rule
        variants: list[str] = []   # only with a final "a" for an unwritten vowel
        for cand in raw:
            if not isinstance(cand, str):
                continue
            cand = " ".join(unicodedata.normalize("NFC", cand).split())
            if target == "hi":
                cand = normalize_spelling(cand) or ""
            if not cand or cand in exact or cand in variants or script_language(cand) != target:
                continue
            if {source, target} != {"en", "hi"}:
                exact.append(cand)
                continue
            english, devanagari = (text, cand) if source == "en" else (cand, text)
            if sounds_the_same(english, devanagari) is None:
                exact.append(cand)
            elif sounds_the_same(english, devanagari, final_a_optional=True) is None:
                # The person picks, so a final "a" variant (Tathagat /
                # Tathagata) is offered — but always after the strict
                # spellings, so अक्षय lists "Akshay" before "Akshaya".
                variants.append(cand)
            else:
                log.info("name suggestion %r for %r dropped: changed sound", cand, text)
        return (exact + variants)[:NAME_SUGGESTIONS_MAX]
