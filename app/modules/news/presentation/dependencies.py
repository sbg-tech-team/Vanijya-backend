"""
FastAPI dependency factories for the news module.

Wires infrastructure (DB session, Redis, adapters) to use cases. All
dependencies are injected into route handlers — no use case is instantiated
inside a route.

Profile context (role_id, commodity_interests, home_state) is queried
directly here, mirroring app_v1_backup's
news_new/feed/service.py::_get_profile_context exactly — there is no shared
`get_profile_attrs` helper in this codebase.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import redis
from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database.session import SessionLocal
from app.modules.chat.application.use_cases.deliver_shared_content import (
    DeliverSharedContentUseCase,
)
from app.modules.chat.presentation.dependencies import get_deliver_shared_content_uc
from app.core.redis_client import get_redis
from app.dependencies import get_current_profile_id, get_current_user_id, get_db
from app.modules.news.application.jobs import (
    run_archive_job,
    run_news_pipeline,
    run_trending_job,
)
from app.modules.news.application.use_cases.enrich_articles import EnrichArticlesUseCase
from app.modules.news.application.use_cases.get_article_detail import GetArticleDetailUseCase
from app.modules.news.application.use_cases.get_feed import GetFeedUseCase
from app.modules.news.application.use_cases.ingest_articles import IngestArticlesUseCase
from app.modules.news.application.use_cases.record_interaction import RecordInteractionUseCase
from app.modules.news.application.use_cases.send_article import SendArticleUseCase
from app.modules.news.data.adapters.gnews import GNewsProvider
from app.modules.news.data.adapters.groq import GroqEnricher
from app.modules.news.data.repository import NewsRepository
from app.modules.news.recommendation.engine import NewsRecommendationEngine
from app.modules.profile.domain.interfaces.repository import IProfileRepository
from app.modules.profile.presentation.dependencies import get_profile_repo


# ── Profile context ───────────────────────────────────────────────────────────

@dataclass
class ProfileContext:
    profile_id: int
    user_id: UUID
    role_id: int | None
    commodity_interests: list[str]
    home_state: str | None


def get_profile_context(
    profile_id: int = Depends(get_current_profile_id),
    user_id: UUID = Depends(get_current_user_id),
    profile_repo: IProfileRepository = Depends(get_profile_repo),
) -> ProfileContext:
    """Role, commodities and home state for feed personalisation.

    Read through the profile module's repository — its entity already carries
    business + named commodities, so news never touches profile's tables.
    """
    profile = profile_repo.get_profile_by_id(profile_id)
    if profile is None:
        return ProfileContext(
            profile_id=profile_id, user_id=user_id, role_id=None,
            commodity_interests=[], home_state=None,
        )

    return ProfileContext(
        profile_id=profile_id,
        user_id=user_id,
        role_id=profile.role_id,
        commodity_interests=[
            pc.commodity.name for pc in profile.commodities if pc.commodity
        ],
        home_state=profile.business.state if profile.business else None,
    )


ProfileContextDep = Annotated[ProfileContext, Depends(get_profile_context)]
DbDep = Annotated[Session, Depends(get_db)]
RedisDep = Annotated[redis.Redis, Depends(get_redis)]


# ── Use case factories ────────────────────────────────────────────────────────

def get_repo(db: DbDep) -> NewsRepository:
    return NewsRepository(db)


def get_engine(db: DbDep) -> NewsRecommendationEngine:
    return NewsRecommendationEngine(NewsRepository(db))


def get_feed_use_case(
    repo: NewsRepository = Depends(get_repo),
    engine: NewsRecommendationEngine = Depends(get_engine),
) -> GetFeedUseCase:
    return GetFeedUseCase(repo=repo, engine=engine)


def get_article_detail_use_case(
    repo: NewsRepository = Depends(get_repo),
) -> GetArticleDetailUseCase:
    return GetArticleDetailUseCase(repo=repo)


def get_record_interaction_use_case(
    repo: NewsRepository = Depends(get_repo),
) -> RecordInteractionUseCase:
    return RecordInteractionUseCase(repo=repo)


def get_send_article_use_case(
    repo: NewsRepository = Depends(get_repo),
    deliver_uc: DeliverSharedContentUseCase = Depends(get_deliver_shared_content_uc),
) -> SendArticleUseCase:
    return SendArticleUseCase(repo=repo, deliver_uc=deliver_uc)


def get_ingest_use_case(
    repo: NewsRepository = Depends(get_repo),
) -> IngestArticlesUseCase:
    return IngestArticlesUseCase(repo=repo, provider=GNewsProvider())


def get_enrich_use_case(
    repo: NewsRepository = Depends(get_repo),
) -> EnrichArticlesUseCase:
    return EnrichArticlesUseCase(repo=repo, enricher=GroqEnricher())


# ── Background-job composition ───────────────────────────────────────────────
# Scheduled jobs have no request scope, so they cannot use Depends(). These are
# the same wiring steps done by hand, each owning its session.

def run_news_pipeline_job() -> dict:
    db = SessionLocal()
    try:
        return run_news_pipeline(NewsRepository(db), GNewsProvider(), GroqEnricher())
    finally:
        db.close()


def run_news_archive_job() -> int:
    db = SessionLocal()
    try:
        return run_archive_job(NewsRepository(db))
    finally:
        db.close()


def run_news_trending_job() -> int:
    db = SessionLocal()
    try:
        return run_trending_job(NewsRepository(db))
    finally:
        db.close()
