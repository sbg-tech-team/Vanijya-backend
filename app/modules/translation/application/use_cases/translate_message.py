from __future__ import annotations

from typing import Optional
from uuid import UUID

from app.modules.translation.application.pipeline import TranslationPipeline
from app.modules.translation.application.use_cases.resolve_target_language import ResolveTargetLanguageUseCase
from app.modules.translation.domain.entities import TranslationResult
from app.modules.translation.domain.exceptions import (
    MessageNotFoundError,
    NotAConversationMemberError,
)
from app.modules.translation.domain.interfaces.context_store import IContextStore
from app.modules.translation.domain.interfaces.repository import ITranslationRepository
from app.modules.translation.domain.interfaces.translation_cache import ITranslationCache
from app.modules.translation.domain.value_objects import AUTO_FALLBACK


class TranslateMessageUseCase:
    """Single-tap — the reader explicitly translates one message they received.
    Never for the reader's own sent messages (caller is responsible for that)."""

    def __init__(
        self,
        repository: ITranslationRepository,
        context_store: IContextStore,
        translation_cache: ITranslationCache,
        pipeline: TranslationPipeline,
        resolve_target_language: ResolveTargetLanguageUseCase,
    ):
        self.repository = repository
        self.context_store = context_store
        self.translation_cache = translation_cache
        self.pipeline = pipeline
        self.resolve_target_language = resolve_target_language

    def execute(
        self,
        reader_id: UUID,
        message_id: UUID,
        explicit_target_lang: Optional[str] = None,
    ) -> TranslationResult:
        message = self.repository.get_message(message_id)
        if message is None or not message.body:
            raise MessageNotFoundError("Message not found or has no text body.")

        # Anyone authenticated can guess or harvest a message id; without this
        # the endpoint hands back the plaintext of any DM or group on the
        # platform. Checked before the engine call so we never pay for it.
        if not self.repository.reader_is_member(reader_id, message.context_type, message.context_id):
            raise NotAConversationMemberError("You do not have access to this message.")

        target = self.resolve_target_language.execute(reader_id, message.context_id, explicit_target_lang)
        context = self.context_store.get_context(message.context_type, message.context_id)

        cache_key_lang = target if target != AUTO_FALLBACK else AUTO_FALLBACK
        fingerprint = context.summary or ""
        cached = self.translation_cache.get(message.body, cache_key_lang, fingerprint)
        if cached is not None:
            return TranslationResult(translated_text=cached, target_lang=target, used_cache=True)

        engine_target = None if target == AUTO_FALLBACK else target
        response = self.pipeline.run(message, engine_target, context)

        resolved_target = target if target != AUTO_FALLBACK else (response.chosen_target_lang or "en")
        self.translation_cache.set(message.body, cache_key_lang, fingerprint, response.translated_text)
        # Durable copy too, so a single tap survives a scroll-back or restart
        # and a second reader wanting the same language pays nothing.
        self.repository.save_translation(message.id, resolved_target, response.translated_text)

        return TranslationResult(translated_text=response.translated_text, target_lang=resolved_target, used_cache=False)
