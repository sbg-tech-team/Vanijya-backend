"""
Groq enricher — OpenAI-compatible chat completion, JSON mode.

One combined call per article returns { classification, summary, impact }.
The LLM never returns role_relevance (computed from the matrix downstream).
Paces itself to stay under the free-tier rate caps.
"""
import json
import logging
import sys
import time

import requests

from app.core.config import settings
from app.modules.news_new.config import (
    ENRICH_ARTICLES_PER_MIN,
    GROQ_MAX_RETRIES,
    GROQ_MODEL,
    GROQ_TEMPERATURE,
    GROQ_TIMEOUT_S,
    GROQ_URL,
    SYSTEM_PROMPT,
)

log = logging.getLogger(__name__)


class RateLimiter:
    """Spaces calls to `per_min` calls/minute (fractional ok)."""

    def __init__(self, per_min: float):
        self.min_interval = 60.0 / per_min if per_min > 0 else 0.0
        self.last = 0.0

    def wait(self) -> None:
        delta = time.time() - self.last
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self.last = time.time()


class GroqEnricher:
    """Concrete intelligence backend. Returns the raw validated-shape LLM dict."""

    def __init__(self, api_key: str | None = None, model: str = GROQ_MODEL,
                 per_min: float = ENRICH_ARTICLES_PER_MIN):
        self.api_key = api_key or settings.GROQ_API_KEY
        self.model = model
        self.limiter = RateLimiter(per_min)

    def enrich(self, text: str) -> dict:
        """Single LLM call. Returns parsed JSON dict (unvalidated enums)."""
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY is not set")
        payload = {
            "model": self.model,
            "temperature": GROQ_TEMPERATURE,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        for attempt in range(GROQ_MAX_RETRIES):
            self.limiter.wait()
            r = requests.post(GROQ_URL, headers=headers, json=payload, timeout=GROQ_TIMEOUT_S)
            if r.status_code == 429:
                retry = float(r.headers.get("retry-after", 2 ** attempt))
                log.warning("Groq 429, backing off %.1fs", retry)
                time.sleep(retry)
                continue
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            return json.loads(content)
        raise RuntimeError("Groq rate limit not clearing after retries.")
