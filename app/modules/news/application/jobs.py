"""
Background job entry points for the news module.

Each function assembles its dependencies from injected primitives and calls the
appropriate use case. These are the callables wired into app.core.scheduler.

Caller pattern (from scheduler):
    from sqlalchemy.orm import Session
    from app.modules.news.application.jobs import run_news_pipeline, run_archive_job

    def scheduled_news_pipeline(db: Session):
        run_news_pipeline(db)

All jobs are re-entrant and safe to call concurrently (each article is committed
individually so a crash mid-batch never loses prior work).
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.modules.news.application.use_cases.enrich_articles import EnrichArticlesUseCase
from app.modules.news.application.use_cases.ingest_articles import IngestArticlesUseCase
from app.modules.news.data.adapters.gnews import GNewsProvider
from app.modules.news.data.adapters.groq import GroqEnricher
from app.modules.news.data.repository import NewsRepository

log = logging.getLogger(__name__)


def run_news_pipeline(db: Session) -> dict:
    """
    Scheduled pipeline: ingest fresh articles, then enrich the pending backlog.
    A quota error during ingest does NOT stop the enrich step.
    Returns a combined stats dict for logging.
    """
    repo = NewsRepository(db)
    provider = GNewsProvider()
    enricher = GroqEnricher()

    ingest_result: dict = {}
    enrich_result: dict = {}

    try:
        ingest_result = IngestArticlesUseCase(repo=repo, provider=provider).execute()
    except Exception:
        log.exception("news pipeline: ingest step failed (continuing to enrich)")
        ingest_result = {"error": "ingest_failed"}

    try:
        enrich_result = EnrichArticlesUseCase(repo=repo, enricher=enricher).execute()
    except Exception:
        log.exception("news pipeline: enrich step failed")
        enrich_result = {"error": "enrich_failed"}

    log.info("news pipeline: ingest=%s enrich=%s", ingest_result, enrich_result)
    return {"ingest": ingest_result, "enrich": enrich_result}


def run_archive_job(db: Session) -> int:
    """
    Daily job: soft-delete articles older than the configured threshold.
    Returns the count of articles archived.
    """
    repo = NewsRepository(db)
    count = repo.archive_old_raw_articles()
    log.info("news archive: archived=%d articles", count)
    return count


def run_trending_job(db: Session) -> int:
    """
    Trending recalculation job. Returns the count of articles in the snapshot.
    """
    from app.modules.news.recommendation.jobs.recalc_trending import recalc_trending
    count = recalc_trending(db)
    log.info("news trending: %d articles in snapshot", count)
    return count
