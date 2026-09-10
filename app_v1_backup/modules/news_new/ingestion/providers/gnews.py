import logging
import time
from datetime import datetime, timezone

import requests

from app.core.config import settings
from app.modules.news_new.config import (
    GNEWS_BASE,
    GNEWS_DEFAULT_COUNTRY,
    GNEWS_FETCH_RETRIES,
    GNEWS_PARAMS,
    GNEWS_TIMEOUT_S,
)
from app.modules.news_new.ingestion.providers.base import BaseNewsProvider, ProviderQuotaError

log = logging.getLogger(__name__)


class GNewsProvider(BaseNewsProvider):
    """GNews /search adapter. Free tier: 100 req/day, max 10 articles/req."""

    name = "gnews"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.GNEWS_API_KEY

    # ── Fetch ────────────────────────────────────────────────────────────────
    def fetch(self, query: str, country: str | None = GNEWS_DEFAULT_COUNTRY) -> list[dict]:
        if not self.api_key:
            raise RuntimeError("GNEWS_API_KEY is not set")
        params = dict(GNEWS_PARAMS, q=query, apikey=self.api_key)
        if country:                       # None/"" -> omit -> global coverage
            params["country"] = country

        for attempt in range(GNEWS_FETCH_RETRIES):
            r = requests.get(GNEWS_BASE, params=params, timeout=GNEWS_TIMEOUT_S)
            if r.status_code == 401:
                raise RuntimeError("GNews 401 — API key invalid or inactive.")
            if r.status_code == 403:
                # 403 = daily quota exhausted; retrying won't help until reset.
                raise ProviderQuotaError("GNews 403 — daily request budget exhausted. Resets 00:00 UTC.")
            if r.status_code == 429:
                # 429 = transient burst/rate limit; back off and retry.
                if attempt < GNEWS_FETCH_RETRIES - 1:
                    retry_after = float(r.headers.get("Retry-After", 2 ** attempt))
                    log.warning("GNews 429 (rate limit), retrying in %.1fs", retry_after)
                    time.sleep(retry_after)
                    continue
                raise ProviderQuotaError("GNews 429 — rate limit not clearing after retries.")
            r.raise_for_status()
            return r.json().get("articles", []) or []
        return []

    # ── Normalize ──────────────────────────────────────────────────────────── #
    def to_canonical(self, raw: dict, query: str | None = None) -> dict:
        src = raw.get("source") or {}
        return {
            "external_id": raw.get("id"),
            "title": raw.get("title"),
            "description": raw.get("description"),
            "content": raw.get("content"),          # truncated on free tier
            "article_url": raw.get("url"),
            "image_url": raw.get("image"),
            "published_at": _parse_dt(raw.get("publishedAt")),
            "language": raw.get("lang"),
            "source_name": src.get("name"),
            "source_url": src.get("url"),
            "source_country": src.get("country"),   # promoted to a real column
            "authors": [],                           # gnews gives none
            "is_duplicate": False,                   # gnews gives no dup flag
            "api_summary": None,                     # gnews has no provider AI summary
            "raw_metadata": {
                "provider": self.name,
                "provider_source_id": src.get("id"),
                "query": query,
                "raw": raw,                          # full provider item, verbatim
            },
        }


def _parse_dt(value: str | None) -> datetime:
    """Parse an ISO-8601 timestamp to a naive UTC datetime (matches our columns)."""
    if not value:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        log.warning("GNews: unparseable publishedAt %r, defaulting to now", value)
        return datetime.now(timezone.utc).replace(tzinfo=None)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt
