from __future__ import annotations

import logging
from dataclasses import replace
from typing import Optional

from app.modules.translation.domain.content import normalize_digits, number_problem, script_problem
from app.modules.translation.domain.entities import ContextSnapshot, EngineResponse, TranslatableMessage
from app.modules.translation.domain.exceptions import TranslationRejectedError
from app.modules.translation.domain.interfaces.context_store import IContextStore
from app.modules.translation.domain.interfaces.engine import ITranslationEngine
from app.modules.translation.domain.interfaces.repository import ITranslationRepository
from app.modules.translation.domain.prompt import LANGUAGE_NAMES, assemble_prompt

log = logging.getLogger(__name__)


class TranslationPipeline:
    """Shared orchestration used by both single-tap and continuous translation:
    fetch the recent-turns window if there's a summary to disambiguate against,
    assemble the layered prompt, call the engine, persist a summary refresh if
    one was due. Callers differ only in how target_lang is resolved and what
    they do with the result (caching, cold-start handling) — that stays in
    each use case, not here.

    The output passes the same checks content translation uses (script,
    words mixing scripts, every number kept) before anyone sees it. A bad
    result is retried once with the same prompt; a second bad one raises
    TranslationRejectedError and nothing — translation or summary — is kept."""

    def __init__(
        self,
        repository: ITranslationRepository,
        context_store: IContextStore,
        engine: ITranslationEngine,
    ):
        self.repository = repository
        self.context_store = context_store
        self.engine = engine

    def run(
        self,
        message: TranslatableMessage,
        target_lang: Optional[str],
        context: ContextSnapshot,
    ) -> EngineResponse:
        recent = []
        if context.summary is not None:
            recent = self.repository.get_preceding_messages(
                message.context_type, message.context_id, message.id, limit=2
            )

        prompt = assemble_prompt(
            summary=context.summary,
            context_messages=recent,
            message_text=message.body,
            target_lang=target_lang,
            request_summary_update=context.due_for_refresh,
        )
        response = self._checked(self.engine.translate(prompt), message, target_lang)
        if response is None:
            response = self._checked(self.engine.translate(prompt), message, target_lang)
        if response is None:
            raise TranslationRejectedError("The translation failed the quality checks twice.")

        if context.due_for_refresh and response.updated_summary:
            self.context_store.save_summary(
                message.context_type, message.context_id, response.updated_summary, message.id
            )

        return response

    @staticmethod
    def _checked(
        response: EngineResponse, message: TranslatableMessage, target_lang: Optional[str]
    ) -> Optional[EngineResponse]:
        """The response with digits normalised to 0-9, or None if it fails a
        check. In auto mode the language is whatever the engine reports it
        chose; if it reported nothing usable only the number check applies."""
        text = normalize_digits(response.translated_text or "")
        lang = target_lang or response.chosen_target_lang
        problem = None
        if not text.strip():
            problem = "empty translation"
        elif lang in LANGUAGE_NAMES:
            problem = script_problem(text, lang)
        problem = problem or number_problem(message.body or "", text)
        if problem:
            log.warning("chat translation of %s (%s) rejected: %s", message.id, lang, problem)
            return None
        return replace(response, translated_text=text)
