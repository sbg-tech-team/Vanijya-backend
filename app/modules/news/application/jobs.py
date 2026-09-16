"""
Background job entry points for the news module.

Each function receives its dependencies already built — the session and the
concrete adapters are composed in news.presentation.dependencies, which is what
app.core.scheduler calls.

All jobs are re-entrant and safe to call concurrently (each article is committed
individually so a crash mid-batch never loses prior work).
"""
from __future__ import annotations

import logging

from app.modules.news.application.use_cases.enrich_articles import EnrichArticlesUseCase
from app.modules.news.application.use_cases.ingest_articles import IngestArticlesUseCase
from app.modules.news.domain.interfaces.enricher import INewsEnricher
from app.modules.news.domain.interfaces.news_provider import INewsProvider
from app.modules.news.domain.interfaces.repository import INewsRepository

log = logging.getLogger(__name__)


def run_news_pipeline(
    repo: INewsRepository,
    provider: INewsProvider,
    enricher: INewsEnricher,
) -> dict:
    """
    Scheduled pipeline: ingest fresh articles, then enrich the pending backlog.
    A quota error during ingest does NOT stop the enrich step.
    Returns a combined stats dict for logging.
    """
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


def run_archive_job(repo: INewsRepository) -> int:
    """
    Daily job: soft-delete articles older than the configured threshold.
    Returns the count of articles archived.
    """
    count = repo.archive_old_raw_articles()
    log.info("news archive: archived=%d articles", count)
    return count


def run_trending_job(repo: INewsRepository) -> int:
    """
    Trending recalculation job. Returns the count of articles in the snapshot.
    """
    count = repo.recalc_trending()
    log.info("news trending: %d articles in snapshot", count)
    return count
