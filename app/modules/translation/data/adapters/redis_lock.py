from __future__ import annotations

import logging
import uuid

import redis as redis_lib

from app.modules.translation.domain.interfaces.translation_lock import ITranslationLock

log = logging.getLogger(__name__)

# Delete only if we still own it: after a TTL expiry someone else may hold the
# key, and a blind DEL would hand their lock to a third caller.
_RELEASE_IF_OWNER = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


class RedisTranslationLock(ITranslationLock):
    """SET NX EX per key. Fails open: with Redis down every caller gets the
    lock, which at worst pays for a duplicate translation."""

    def __init__(self, client: redis_lib.Redis):
        self._client = client
        self._tokens: dict[str, str] = {}

    def acquire(self, key: str, ttl_seconds: int) -> bool:
        token = uuid.uuid4().hex
        try:
            got = bool(self._client.set(f"lock:{key}", token, nx=True, ex=ttl_seconds))
        except Exception as exc:
            log.warning("translation lock unavailable, proceeding without it: %s", exc)
            return True
        if got:
            self._tokens[key] = token
        return got

    def release(self, key: str) -> None:
        token = self._tokens.pop(key, None)
        if token is None:
            return
        try:
            self._client.eval(_RELEASE_IF_OWNER, 1, f"lock:{key}", token)
        except Exception as exc:
            # The TTL frees it anyway.
            log.warning("translation lock release failed for %s: %s", key, exc)
