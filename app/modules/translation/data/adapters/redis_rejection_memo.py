from __future__ import annotations

import logging

import redis as redis_lib

from app.modules.translation.domain.interfaces.rejection_memo import IRejectionMemo

log = logging.getLogger(__name__)


class RedisRejectionMemo(IRejectionMemo):
    """One key per rejected (message, language), expiring on its own. Fails
    open: with Redis down nothing is remembered and nothing is skipped."""

    def __init__(self, client: redis_lib.Redis):
        self._client = client

    def seen(self, key: str) -> bool:
        try:
            return bool(self._client.exists(f"rejected:{key}"))
        except Exception as exc:
            log.warning("rejection memo unavailable, not skipping: %s", exc)
            return False

    def remember(self, key: str, ttl_seconds: int) -> None:
        try:
            self._client.set(f"rejected:{key}", 1, ex=ttl_seconds)
        except Exception as exc:
            log.warning("rejection memo unavailable, not recorded: %s", exc)
