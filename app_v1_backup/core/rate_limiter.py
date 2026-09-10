"""
Redis sliding-window rate limiter.

Usage in a route:
    from app.core.rate_limiter import RateLimiter
    from app.core.redis_client import get_redis

    limiter = RateLimiter()

    @router.post("/some-endpoint")
    def endpoint(request: Request, redis=Depends(get_redis)):
        limiter.check(redis, f"ip:{request.client.host}", limit=10, window=60)
        ...
"""
from __future__ import annotations

import time
import uuid

import redis as redis_lib
from fastapi import HTTPException


class RateLimiter:
    """Sliding-window counter backed by a Redis sorted set."""

    def check(
        self,
        client: redis_lib.Redis,
        key: str,
        limit: int,
        window: int,
    ) -> None:
        """
        Raise HTTP 429 if `key` has exceeded `limit` requests in the last
        `window` seconds. Otherwise, record the current request and return.
        """
        now = time.time()
        window_start = now - window
        full_key = f"rl:{key}"

        pipe = client.pipeline()
        # Drop entries older than the window
        pipe.zremrangebyscore(full_key, "-inf", window_start)
        # Record this request (unique member so concurrent calls don't collide)
        pipe.zadd(full_key, {str(uuid.uuid4()): now})
        # Count requests in window
        pipe.zcard(full_key)
        # Auto-expire the key so Redis doesn't accumulate stale sets
        pipe.expire(full_key, window + 1)
        results = pipe.execute()

        count: int = results[2]
        if count > limit:
            raise HTTPException(
                status_code=429,
                detail=f"Too many requests. Retry after {window} seconds.",
                headers={"Retry-After": str(window)},
            )

    def remaining(
        self,
        client: redis_lib.Redis,
        key: str,
        limit: int,
        window: int,
    ) -> int:
        """Return how many requests are left in the current window (non-mutating)."""
        now = time.time()
        window_start = now - window
        full_key = f"rl:{key}"

        pipe = client.pipeline()
        pipe.zremrangebyscore(full_key, "-inf", window_start)
        pipe.zcard(full_key)
        results = pipe.execute()

        used: int = results[1]
        return max(0, limit - used)


# Shared singleton — import and call `.check()` anywhere
rate_limiter = RateLimiter()
