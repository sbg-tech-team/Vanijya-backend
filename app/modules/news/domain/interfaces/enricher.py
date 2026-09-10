"""
Abstract contract for the article enrichment backend.

GroqEnricher (data/adapters/groq.py) implements this.
The adapter owns: text construction, LLM call, JSON parsing, retry logic,
and mapping the raw LLM output to an EnrichedArticle domain entity.
The application use case (enrich_articles.py) only sees this interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.modules.news.domain.entities import EnrichedArticle, RawArticle


class INewsEnricher(ABC):

    #: Model identifier string, used for logging and model_version column.
    model: str = "base"

    @abstractmethod
    def enrich(self, raw_article: RawArticle) -> EnrichedArticle:
        """
        Enrich one raw article and return a fully populated EnrichedArticle
        domain entity ready for persistence.

        The adapter is responsible for:
          - Building the input text from raw_article fields.
          - Calling the LLM API with the classification + summary prompt.
          - Validating and parsing the JSON response.
          - Retrying on transient failures (up to adapter-defined max).
          - Computing role_trader / role_broker / role_exporter from
            the RELEVANCY_MATRIX using the classified primary_factor.

        Raises:
            EnrichmentError – all retries exhausted; article should be marked FAILED.
        """
