from abc import ABC, abstractmethod


class ProviderError(RuntimeError):
    """Base for provider fetch errors."""


class ProviderQuotaError(ProviderError):
    """Daily request budget / rate cap exhausted (e.g. GNews 429/403). Stop fetching THIS run."""


class BaseNewsProvider(ABC):
    """
    A news source provider. Each provider knows how to fetch from its API and
    how to normalize one raw item into the canonical article dict.

    The canonical dict is the ONLY shape that leaves a provider — no provider
    JSON shape may leak past `to_canonical`. Adding a provider = one subclass,
    zero changes elsewhere.

    Canonical dict keys:
        external_id, title, description, content, article_url, image_url,
        published_at (datetime, UTC), language, source_name, source_url,
        source_country, authors (list[str]), is_duplicate (bool),
        api_summary (str|None), raw_metadata (dict)
    """

    name: str = "base"

    @abstractmethod
    def fetch(self, query: str, country: str | None = None) -> list[dict]:
        """
        One API call. Returns the provider's raw article items (verbatim).
        `country`: ISO code to bias results, or None for global coverage.
        """
        raise NotImplementedError

    @abstractmethod
    def to_canonical(self, raw: dict, query: str | None = None) -> dict:
        """Normalize one raw provider item into the canonical article dict."""
        raise NotImplementedError
