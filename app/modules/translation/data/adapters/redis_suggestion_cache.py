from __future__ import annotations

import json
import logging
from typing import Optional

import redis as redis_lib

from app.modules.translation.domain.interfaces.suggestion_cache import ISuggestionCache

log = logging.getLogger(__name__)


class RedisSuggestionCache(ISuggestionCache):
    """JSON list per key, expiring on its own. Fails open."""

    def __init__(self, client: redis_lib.Redis):
        self._client = client

    def get(self, key: str) -> Optional[list[str]]:
        try:
            raw = self._client.get(f"name_suggest:{key}")
        except Exception as exc:
            log.warning("suggestion cache unavailable: %s", exc)
            return None
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except ValueError:
            return None
        return value if isinstance(value, list) else None

    def set(self, key: str, value: list[str], ttl_seconds: int) -> None:
        try:
            self._client.set(f"name_suggest:{key}", json.dumps(value, ensure_ascii=False), ex=ttl_seconds)
        except Exception as exc:
            log.warning("suggestion cache unavailable, not stored: %s", exc)
