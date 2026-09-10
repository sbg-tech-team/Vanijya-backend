"""
Ingest use case: run one rotation of the GNews query pool.

Flow per run:
  1. Ask the provider which queries to execute this slot.
  2. Fetch articles for each query (honouring provider rate-limit semantics).
  3. Save each article (dedup by external_id — ON CONFLICT DO NOTHING).
  4. Return a stats dict for logging / admin endpoint.

Pacing between queries is enforced by sleeping `inter_query_delay` seconds
(default 5 s, from GNews free-tier guidance). A ProviderQuotaError on any
query stops the run cleanly so we don't burn remaining daily budget.
"""
from __future__ import annotations

import logging
import time

from app.modules.news.domain.exceptions import ProviderQuotaError
from app.modules.news.domain.interfaces.news_provider import INewsProvider
from app.modules.news.domain.interfaces.repository import INewsRepository

log = logging.getLogger(__name__)

_INTER_QUERY_DELAY_S = 5.0


class IngestArticlesUseCase:

    def __init__(
        self,
        repo: INewsRepository,
        provider: INewsProvider,
        inter_query_delay: float = _INTER_QUERY_DELAY_S,
    ) -> None:
        self._repo = repo
        self._provider = provider
        self._delay = inter_query_delay

    def execute(self) -> dict:
        queries = self._provider.select_queries_for_run()
        saved = 0
        skipped = 0
        errors = 0
        queries_run = 0

        for i, q in enumerate(queries):
            try:
                articles = self._provider.fetch_articles(
                    query=q["q"],
                    country=q.get("country"),
                )
            except ProviderQuotaError:
                log.warning(
                    "ingest: quota exhausted on query %d/%d, stopping run",
                    i + 1, len(queries),
                )
                break
            except Exception as exc:
                log.error("ingest: query %d/%d failed: %s", i + 1, len(queries), exc)
                errors += 1
                if i < len(queries) - 1:
                    time.sleep(self._delay)
                continue

            queries_run += 1
            for article in articles:
                try:
                    before_id = article.id
                    saved_article = self._repo.save_raw_article(article)
                    # save_raw_article commits internally per article
                    if saved_article.id != before_id:
                        # existing row returned — dedup hit
                        skipped += 1
                    else:
                        saved += 1
                except Exception as exc:
                    log.error("ingest: save failed for %s: %s", article.external_id, exc)
                    self._repo.rollback()
                    errors += 1

            if i < len(queries) - 1:
                time.sleep(self._delay)

        log.info(
            "ingest complete: queries_run=%d saved=%d skipped=%d errors=%d",
            queries_run, saved, skipped, errors,
        )
        return {
            "provider": self._provider.name,
            "queries_run": queries_run,
            "saved": saved,
            "skipped": skipped,
            "errors": errors,
        }
