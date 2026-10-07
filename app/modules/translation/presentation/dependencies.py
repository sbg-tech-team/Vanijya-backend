from datetime import timedelta

from fastapi import Depends
from sqlalchemy.orm import Session

import redis

from app.core.config import settings
from app.core.redis_client import get_redis
from app.dependencies import get_db
from app.modules.translation.application.pipeline import TranslationPipeline
from app.modules.translation.application.use_cases.handle_incoming_message import HandleIncomingMessageUseCase
from app.modules.translation.application.use_cases.resolve_content_language import ResolveContentLanguageUseCase
from app.modules.translation.application.use_cases.resolve_target_language import ResolveTargetLanguageUseCase
from app.modules.translation.application.use_cases.toggle_continuous import ToggleContinuousTranslationUseCase
from app.modules.translation.application.use_cases.translate_content import TranslateContentUseCase
from app.modules.translation.application.use_cases.translate_message import TranslateMessageUseCase
from app.modules.translation.application.use_cases.translation_preference import TranslationPreferenceUseCase
from app.modules.translation.data.adapters.gemini_engine import GeminiTranslationEngine
from app.modules.translation.data.adapters.inmemory_cache import InMemoryTranslationCache
from app.modules.translation.data.adapters.redis_lock import RedisTranslationLock
from app.modules.translation.data.adapters.redis_rejection_memo import RedisRejectionMemo
from app.modules.translation.data.content_repository import ContentTranslationRepository
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
    rc: redis.Redis = Depends(get_redis),
) -> HandleIncomingMessageUseCase:
    """Also called directly (not through Depends) by chat's background task,
    which must then pass `rc` itself."""
    return HandleIncomingMessageUseCase(repository=repo, context_store=repo, pipeline=pipeline,
                                        rejection_memo=RedisRejectionMemo(rc))


def get_toggle_continuous_uc(
    repo: TranslationRepository = Depends(get_translation_repo),
    resolve: ResolveTargetLanguageUseCase = Depends(get_resolve_target_language_uc),
) -> ToggleContinuousTranslationUseCase:
    return ToggleContinuousTranslationUseCase(repository=repo, resolve_target_language=resolve)


# ── Content (post / comment / news) translation ─────────────────────────────
# Same engine singleton as chat: one client, one model setting, one key.

def get_content_translation_repo(db: Session = Depends(get_db)) -> ContentTranslationRepository:
    return ContentTranslationRepository(db)


def get_translate_content_uc(
    repo: ContentTranslationRepository = Depends(get_content_translation_repo),
    rc: redis.Redis = Depends(get_redis),
) -> TranslateContentUseCase:
    return TranslateContentUseCase(repository=repo, engine=_engine, lock=RedisTranslationLock(rc))


def get_resolve_content_language_uc(
    repo: TranslationRepository = Depends(get_translation_repo),
) -> ResolveContentLanguageUseCase:
    return ResolveContentLanguageUseCase(repo)


def get_translation_preference_uc(
    repo: TranslationRepository = Depends(get_translation_repo),
) -> TranslationPreferenceUseCase:
    return TranslationPreferenceUseCase(repo)


# ── Scheduled-job composition ────────────────────────────────────────────────
# A scheduled job runs with no request, so it owns its session — the same
# pattern calling/presentation/dependencies.py uses for its sweeps.

def run_translation_retry_job() -> dict:
    """Re-translate messages whose live BackgroundTask never completed."""
    from app.core.database.session import SessionLocal
    from app.modules.translation.application.jobs import run_translation_retry

    db = SessionLocal()
    try:
        repo = TranslationRepository(
            db,
            refresh_every_n_messages=settings.TRANSLATION_SUMMARY_REFRESH_EVERY_N_MESSAGES,
            refresh_ttl=timedelta(hours=settings.TRANSLATION_SUMMARY_REFRESH_TTL_HOURS),
        )
        uc = HandleIncomingMessageUseCase(
            repository=repo, context_store=repo,
            pipeline=TranslationPipeline(repository=repo, context_store=repo, engine=_engine),
            rejection_memo=RedisRejectionMemo(get_redis()),
        )
        return run_translation_retry(repo, uc.execute)
    finally:
        db.close()
