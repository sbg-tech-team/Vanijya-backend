"""
Sync Redis client — used by the home feed (session taste + seen-sets).

The client is created once at module load from REDIS_URL in settings.
FastAPI dependency: Depends(get_redis) → yields the shared client.
"""
from __future__ import annotations

import redis

from app.core.config import settings

_client: redis.Redis | None = None


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(
            settings.REDIS_URL,
            decode_responses=False,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
    return _client


def get_redis() -> redis.Redis:
    """FastAPI dependency — yields the shared Redis client."""
    return _get_client()
