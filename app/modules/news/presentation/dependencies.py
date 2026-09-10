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
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.redis_client import get_redis
from app.dependencies import get_current_profile_id, get_current_user_id, get_db
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
from app.modules.profile.data.models import Business, Commodity, Profile, Profile_Commodity


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
    db: Session = Depends(get_db),
) -> ProfileContext:
    profile = db.execute(
        select(Profile).where(Profile.id == profile_id)
    ).scalar_one_or_none()
    role_id = profile.role_id if profile else None

    commodity_interests: list[str] = list(
        db.execute(
            select(Commodity.name)
            .join(Profile_Commodity, Profile_Commodity.commodity_id == Commodity.id)
            .where(Profile_Commodity.profile_id == profile_id)
        ).scalars()
    )
    home_state: str | None = db.execute(
        select(Business.state).where(Business.profile_id == profile_id)
    ).scalar_one_or_none()

    return ProfileContext(
        profile_id=profile_id,
        user_id=user_id,
        role_id=role_id,
        commodity_interests=commodity_interests,
        home_state=home_state,
    )


ProfileContextDep = Annotated[ProfileContext, Depends(get_profile_context)]
DbDep = Annotated[Session, Depends(get_db)]
RedisDep = Annotated[redis.Redis, Depends(get_redis)]


# ── Use case factories ────────────────────────────────────────────────────────

def get_repo(db: DbDep) -> NewsRepository:
    return NewsRepository(db)


def get_engine(db: DbDep) -> NewsRecommendationEngine:
    return NewsRecommendationEngine(db)


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
) -> SendArticleUseCase:
    return SendArticleUseCase(repo=repo)


def get_ingest_use_case(
    repo: NewsRepository = Depends(get_repo),
) -> IngestArticlesUseCase:
    return IngestArticlesUseCase(repo=repo, provider=GNewsProvider())


def get_enrich_use_case(
    repo: NewsRepository = Depends(get_repo),
) -> EnrichArticlesUseCase:
    return EnrichArticlesUseCase(repo=repo, enricher=GroqEnricher())
