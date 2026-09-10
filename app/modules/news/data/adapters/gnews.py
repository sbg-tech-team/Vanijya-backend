"""
GNews API adapter — implements INewsProvider.

Free tier: 100 req/day, max 10 articles/req.
Rotation: select_queries_for_run() returns 2 queries per run via time-slot
rotation over the 12-query pool in gnews_queries.py.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone

import requests

from app.core.config import settings
from app.modules.news.domain.entities import RawArticle
from app.modules.news.domain.exceptions import ProviderError, ProviderQuotaError
from app.modules.news.domain.interfaces.news_provider import INewsProvider
from app.modules.news.data.adapters.gnews_queries import QUERY_POOL

log = logging.getLogger(__name__)

# ── Provider constants ────────────────────────────────────────────────────────

_BASE_URL = "https://gnews.io/api/v4/search"
_DEFAULT_COUNTRY = "in"
_PARAMS: dict = {
    "lang": "en",
    "max": 10,
    "in": "title,description",
    "sortby": "publishedAt",
}
_TIMEOUT_S = 30
_FETCH_RETRIES = 3
_INTER_QUERY_DELAY_S = 5.0
_QUERIES_PER_RUN = 2


class GNewsProvider(INewsProvider):

    name = "gnews"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or settings.GNEWS_API_KEY

    # ── INewsProvider ──────────────────────────────────────────────────────────

    def fetch_articles(
        self, query: str, country: str | None = _DEFAULT_COUNTRY
    ) -> list[RawArticle]:
        raw_items = self._fetch_raw(query, country)
        articles: list[RawArticle] = []
        for item in raw_items:
            article = self._normalize(item, query=query)
            if article is not None:
                articles.append(article)
        return articles

    def select_queries_for_run(self) -> list[dict]:
        """
        Time-slot rotation: divide the day into 30-min slots (48 total),
        pick 2 consecutive queries from the pool per slot (wrapping).
        All 12 pool entries are covered in 6 slots = 3 hours.
        """
        now = datetime.now(timezone.utc)
        slot = (now.hour * 2 + now.minute // 30) % len(QUERY_POOL)
        end = slot + _QUERIES_PER_RUN
        if end <= len(QUERY_POOL):
            return QUERY_POOL[slot:end]
        return QUERY_POOL[slot:] + QUERY_POOL[: end - len(QUERY_POOL)]

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _fetch_raw(self, query: str, country: str | None) -> list[dict]:
        if not self._api_key:
            raise RuntimeError("GNEWS_API_KEY is not configured")

        params = dict(_PARAMS, q=query, apikey=self._api_key)
        if country:
            params["country"] = country

        for attempt in range(_FETCH_RETRIES):
            try:
                r = requests.get(_BASE_URL, params=params, timeout=_TIMEOUT_S)
            except requests.RequestException as exc:
                if attempt < _FETCH_RETRIES - 1:
                    log.warning("GNews request error (attempt %d): %s", attempt + 1, exc)
                    time.sleep(2 ** attempt)
                    continue
                raise ProviderError(f"GNews request failed after retries: {exc}") from exc

            if r.status_code == 401:
                raise RuntimeError("GNews 401 — API key invalid or inactive")
            if r.status_code == 403:
                raise ProviderQuotaError(
                    "GNews 403 — daily request budget exhausted. Resets at 00:00 UTC."
                )
            if r.status_code == 429:
                if attempt < _FETCH_RETRIES - 1:
                    wait = float(r.headers.get("Retry-After", 2 ** attempt))
                    log.warning("GNews 429 (rate limit), retrying in %.1fs", wait)
                    time.sleep(wait)
                    continue
                raise ProviderQuotaError(
                    "GNews 429 — rate limit not clearing after retries"
                )

            try:
                r.raise_for_status()
            except requests.HTTPError as exc:
                raise ProviderError(f"GNews HTTP error: {exc}") from exc

            return r.json().get("articles", []) or []

        return []

    def _normalize(self, raw: dict, query: str | None) -> RawArticle | None:
        url = raw.get("url")
        title = raw.get("title")
        if not url or not title:
            return None

        src = raw.get("source") or {}
        return RawArticle(
            id=uuid.uuid4(),
            external_id=raw.get("id") or url,
            title=title,
            description=raw.get("description"),
            content=raw.get("content"),
            article_url=url,
            image_url=raw.get("image"),
            published_at=_parse_dt(raw.get("publishedAt")),
            language=raw.get("lang"),
            source_name=src.get("name"),
            source_url=src.get("url"),
            source_country=src.get("country"),
            authors=[],
            is_duplicate=False,
            api_summary=None,
            raw_metadata={
                "provider": self.name,
                "provider_source_id": src.get("id"),
                "query": query,
                "raw": raw,
            },
        )


def _parse_dt(value: str | None) -> datetime:
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
