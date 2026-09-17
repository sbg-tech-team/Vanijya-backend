from __future__ import annotations

from typing import Optional

from app.modules.translation.domain.entities import ContextSnapshot, EngineResponse, TranslatableMessage
from app.modules.translation.domain.interfaces.context_store import IContextStore
from app.modules.translation.domain.interfaces.engine import ITranslationEngine
from app.modules.translation.domain.interfaces.repository import ITranslationRepository
from app.modules.translation.domain.prompt import assemble_prompt


class TranslationPipeline:
    """Shared orchestration used by both single-tap and continuous translation:
    fetch the recent-turns window if there's a summary to disambiguate against,
    assemble the layered prompt, call the engine, persist a summary refresh if
    one was due. Callers differ only in how target_lang is resolved and what
    they do with the result (caching, cold-start handling) — that stays in
    each use case, not here."""

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
        response = self.engine.translate(prompt)

        if context.due_for_refresh and response.updated_summary:
            self.context_store.save_summary(
                message.context_type, message.context_id, response.updated_summary, message.id
            )

        return response
