"""
Abstract contract for any external news source provider.

GNewsProvider (data/adapters/gnews.py) implements this.
Swap in any other provider (RSS, NewsData, etc.) by writing a new adapter
that inherits from INewsProvider — nothing else in the module changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.modules.news.domain.entities import RawArticle


class INewsProvider(ABC):

    #: Human-readable name used in logs and ingestion stats.
    name: str = "base"

    @abstractmethod
    def fetch_articles(
        self,
        query: str,
        country: str | None = None,
    ) -> list[RawArticle]:
        """
        Execute one API call for the given query and return normalised domain
        entities. The adapter owns: HTTP call, pagination/limits, field
        normalisation, and dedup of items within a single response.

        Raises:
            ProviderQuotaError  – daily budget / 429 exhausted; stop this run.
            ProviderError       – any other fetch / parse failure.
        """

    @abstractmethod
    def select_queries_for_run(self) -> list[dict]:
        """
        Return the subset of the rotation query pool to execute in this run.
        Each dict: {"q": <GNews query string>, "country": "in" | None}.
        The adapter applies time-slot rotation so the full pool is covered
        over the day without blowing the free-tier budget.
        """
