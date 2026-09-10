"""
Domain exceptions for the news module.

All exceptions raised in data/, application/, and recommendation/ layers
must be one of these types. The presentation layer catches them and maps
them to HTTP status codes — no HTTPException anywhere below presentation/.
"""
from __future__ import annotations


class NewsBaseError(Exception):
    """Root exception for the news module."""


# ── Article lifecycle ─────────────────────────────────────────────────────────

class ArticleNotFoundError(NewsBaseError):
    """The requested article_id does not exist in the database."""


class ArticleNotEnrichedError(NewsBaseError):
    """
    The article exists but has not been through the enrichment pipeline yet.
    Raised when feed scoring requires enrichment fields that are not present.
    """


# ── Ingestion pipeline ────────────────────────────────────────────────────────

class ProviderQuotaError(NewsBaseError):
    """
    The external news provider (e.g. GNews) has exhausted its daily request
    budget or returned a 429. The current ingestion run should stop cleanly.
    """


class ProviderError(NewsBaseError):
    """
    A non-quota fetch error from the external provider (network, parse, etc.).
    Individual article failures may be swallowed; full-run failures raise this.
    """


class IngestError(NewsBaseError):
    """General ingestion pipeline error not covered by the above."""


# ── Enrichment pipeline ───────────────────────────────────────────────────────

class EnrichmentError(NewsBaseError):
    """
    The LLM enricher (e.g. Groq) failed after all retries for a given article.
    The article is marked FAILED in the pipeline; other articles continue.
    """


# ── Profile / user context ────────────────────────────────────────────────────

class ProfileNotFoundError(NewsBaseError):
    """
    No profile row found for the given profile_id.
    Raised when the feed or interaction layer needs profile context.
    """
