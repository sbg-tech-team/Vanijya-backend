from __future__ import annotations

from typing import Optional
from uuid import UUID

from app.modules.translation.application.pipeline import TranslationPipeline
from app.modules.translation.domain.entities import TranslationResult
from app.modules.translation.domain.interfaces.context_store import IContextStore
from app.modules.translation.domain.interfaces.repository import ITranslationRepository


class HandleIncomingMessageUseCase:
    """Continuous mode — DMs only, no group fan-out. Call once per receiver right
    when chat has a new message to deliver (e.g. alongside the emit_to_user push
    in chat/presentation/router.py), before groups have any chance to reach
    here. target_lang was already resolved once at opt-in (see
    ToggleContinuousTranslationUseCase) and is reused as-is — this does not
    re-run the resolution chain on every message."""

    def __init__(
        self,
        repository: ITranslationRepository,
        context_store: IContextStore,
        pipeline: TranslationPipeline,
    ):
        self.repository = repository
        self.context_store = context_store
        self.pipeline = pipeline

    def execute(self, receiver_id: UUID, message_id: UUID) -> Optional[TranslationResult]:
        message = self.repository.get_message(message_id)
        if message is None or not message.body or message.context_type != "dm":
            return None

        pref = self.repository.get_conversation_pref(receiver_id, message.context_id)
        if pref is None or not pref.continuous_enabled:
            return None

        context = self.context_store.get_context(message.context_type, message.context_id)
        response = self.pipeline.run(message, pref.target_lang, context)

        resolved_target = pref.target_lang or response.chosen_target_lang or "en"
        # Persist before emitting: the socket event is fire-and-forget, so if
        # the reader is offline or the socket drops this row is the only copy.
        self.repository.save_translation(message.id, resolved_target, response.translated_text)
        return TranslationResult(translated_text=response.translated_text, target_lang=resolved_target, used_cache=False)
