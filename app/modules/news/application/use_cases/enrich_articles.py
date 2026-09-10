"""
Enrich use case: process pending raw articles through the LLM pipeline.

Flow per batch:
  1. Fetch up to `limit` articles with status=PENDING.
  2. Mark each as PROCESSING (committed immediately — prevents double-processing
     if a second job fires while this one runs).
  3. Enrich via INewsEnricher, save the result, mark ENRICHED.
  4. On failure: mark FAILED (article is skipped in future runs unless reset).
  5. Pace calls to stay under the free-tier LLM rate cap.

Pacing: `articles_per_min` controls the target throughput (default 2/min).
"""
from __future__ import annotations

import logging
import time

from app.modules.news.domain.exceptions import EnrichmentError
from app.modules.news.domain.interfaces.enricher import INewsEnricher
from app.modules.news.domain.interfaces.repository import INewsRepository
from app.modules.news.domain.value_objects import IntelligenceStatus

log = logging.getLogger(__name__)

_BATCH_LIMIT = 20
_ARTICLES_PER_MIN = 2.0


class EnrichArticlesUseCase:

    def __init__(
        self,
        repo: INewsRepository,
        enricher: INewsEnricher,
        limit: int = _BATCH_LIMIT,
        articles_per_min: float = _ARTICLES_PER_MIN,
    ) -> None:
        self._repo = repo
        self._enricher = enricher
        self._limit = limit
        self._min_interval = 60.0 / articles_per_min

    def execute(self) -> dict:
        articles = self._repo.get_pending_raw_articles(limit=self._limit)
        enriched_count = 0
        failed_count = 0

        for i, article in enumerate(articles):
            # Mark processing immediately so concurrent jobs don't double-process
            self._repo.mark_intelligence_status(article.id, IntelligenceStatus.PROCESSING)
            self._repo.commit()

            t_start = time.monotonic()
            try:
                enriched = self._enricher.enrich(article)
                self._repo.save_enriched_article(enriched)  # commits internally
                self._repo.mark_intelligence_status(article.id, IntelligenceStatus.ENRICHED)
                self._repo.commit()
                enriched_count += 1
                log.debug("enriched article %s (%s)", article.id, article.title[:60])
            except EnrichmentError as exc:
                self._repo.rollback()
                self._repo.mark_intelligence_status(article.id, IntelligenceStatus.FAILED)
                self._repo.commit()
                failed_count += 1
                log.error("enrich failed for %s: %s", article.id, exc)
            except Exception as exc:
                self._repo.rollback()
                self._repo.mark_intelligence_status(article.id, IntelligenceStatus.FAILED)
                self._repo.commit()
                failed_count += 1
                log.exception("unexpected enrich error for %s: %s", article.id, exc)

            # Pace to stay under LLM rate cap
            elapsed = time.monotonic() - t_start
            if i < len(articles) - 1 and elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)

        log.info(
            "enrich complete: enriched=%d failed=%d total=%d",
            enriched_count, failed_count, len(articles),
        )
        return {
            "model": self._enricher.model,
            "processed": len(articles),
            "enriched": enriched_count,
            "failed": failed_count,
        }
