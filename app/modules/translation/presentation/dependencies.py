from datetime import timedelta

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.dependencies import get_db
from app.modules.translation.application.pipeline import TranslationPipeline
from app.modules.translation.application.use_cases.handle_incoming_message import HandleIncomingMessageUseCase
from app.modules.translation.application.use_cases.resolve_target_language import ResolveTargetLanguageUseCase
from app.modules.translation.application.use_cases.toggle_continuous import ToggleContinuousTranslationUseCase
from app.modules.translation.application.use_cases.translate_message import TranslateMessageUseCase
from app.modules.translation.data.adapters.gemini_engine import GeminiTranslationEngine
from app.modules.translation.data.adapters.inmemory_cache import InMemoryTranslationCache
from app.modules.translation.data.repository import TranslationRepository

# Process-lifetime singletons — must not be recreated per request, or they'd
# never actually cache/reuse anything across calls.
_engine = GeminiTranslationEngine(api_key=settings.GEMINI_API_KEY, model=settings.TRANSLATION_GEMINI_MODEL)
_translation_cache = InMemoryTranslationCache()


def get_translation_repo(db: Session = Depends(get_db)) -> TranslationRepository:
    return TranslationRepository(
        db,
        refresh_every_n_messages=settings.TRANSLATION_SUMMARY_REFRESH_EVERY_N_MESSAGES,
        refresh_ttl=timedelta(hours=settings.TRANSLATION_SUMMARY_REFRESH_TTL_HOURS),
    )


def get_translation_pipeline(
    repo: TranslationRepository = Depends(get_translation_repo),
) -> TranslationPipeline:
    return TranslationPipeline(repository=repo, context_store=repo, engine=_engine)


def get_resolve_target_language_uc(
    repo: TranslationRepository = Depends(get_translation_repo),
) -> ResolveTargetLanguageUseCase:
    return ResolveTargetLanguageUseCase(repo)


def get_translate_message_uc(
    repo: TranslationRepository = Depends(get_translation_repo),
    pipeline: TranslationPipeline = Depends(get_translation_pipeline),
    resolve: ResolveTargetLanguageUseCase = Depends(get_resolve_target_language_uc),
) -> TranslateMessageUseCase:
    return TranslateMessageUseCase(
        repository=repo,
        context_store=repo,
        translation_cache=_translation_cache,
        pipeline=pipeline,
        resolve_target_language=resolve,
    )


def get_handle_incoming_message_uc(
    repo: TranslationRepository = Depends(get_translation_repo),
    pipeline: TranslationPipeline = Depends(get_translation_pipeline),
) -> HandleIncomingMessageUseCase:
    return HandleIncomingMessageUseCase(repository=repo, context_store=repo, pipeline=pipeline)


def get_toggle_continuous_uc(
    repo: TranslationRepository = Depends(get_translation_repo),
    resolve: ResolveTargetLanguageUseCase = Depends(get_resolve_target_language_uc),
) -> ToggleContinuousTranslationUseCase:
    return ToggleContinuousTranslationUseCase(repository=repo, resolve_target_language=resolve)
