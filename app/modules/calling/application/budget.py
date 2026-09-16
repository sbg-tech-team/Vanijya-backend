"""Spend guardrails for calling.

Stream bills on PARTICIPANT-MINUTES: participants x wall-clock duration. A
forgotten call therefore bills forever, and a 20-person group call bills 20x as
fast as a 1:1. Surprise bills come from exactly three places:

  1. calls that never end            -> bounded by duration caps (value_objects)
  2. one user or client looping      -> bounded by PER_USER_DAILY_MINUTES
  3. everything at once / an attack  -> bounded by PLATFORM_MONTHLY_MINUTES

This module owns 2 and 3. Counters live in Redis with natural expiry, so there
is no cleanup job and no table.

Design rule: a Redis outage must NEVER block calling. Every read fails OPEN
(calls allowed) and every write fails silent. The circuit breaker is a cost
guardrail, not a security control — the hard ceilings that survive an outage are
the duration caps enforced by Stream itself.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import redis as redis_lib

log = logging.getLogger(__name__)

# ── Budgets ───────────────────────────────────────────────────────────────────
# Sized against Stream audio pricing: $0.30 per 1,000 participant-minutes.
#
#   PER_USER_DAILY_MINUTES  = 600   -> 10 h/day of 1:1 talk time per user.
#                                      Generous for a human, tight for a loop.
#   PLATFORM_MONTHLY_MINUTES= 300_000 -> ~$90/month ceiling. Stream's free tier
#                                      is $100/month of credit, so the default
#                                      keeps the whole platform inside it.
#
# Raise deliberately, with the cost in mind. Both are overridable via Settings.

PER_USER_DAILY_MINUTES: int = 600
PLATFORM_MONTHLY_MINUTES: int = 300_000

#: Warn in the logs once usage crosses this fraction of the monthly budget.
PLATFORM_WARN_RATIO: float = 0.80

_USER_KEY_TTL = 172_800      # 2 days — covers the day key plus timezone slop
_PLATFORM_KEY_TTL = 3_456_000  # 40 days — covers the month key


def _day(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y%m%d")


def _month(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y%m")


def _user_key(user_id) -> str:
    return f"calls:minutes:user:{user_id}:{_day()}"


def _platform_key() -> str:
    return f"calls:minutes:platform:{_month()}"


def _limits() -> tuple[int, int]:
    """Read budgets from Settings when available, else the module defaults.

    Settings construction can fail (missing DATABASE_URL in a worker, a test
    harness, a management script). This module promises never to raise, so a
    config failure falls back to the defaults rather than taking calling down.
    """
    try:
        from app.core.config import settings
        return (
            int(getattr(settings, "CALLS_PER_USER_DAILY_MINUTES", None) or PER_USER_DAILY_MINUTES),
            int(getattr(settings, "CALLS_PLATFORM_MONTHLY_MINUTES", None) or PLATFORM_MONTHLY_MINUTES),
        )
    except Exception:
        return PER_USER_DAILY_MINUTES, PLATFORM_MONTHLY_MINUTES


# ── Read ──────────────────────────────────────────────────────────────────────

def check_budget(rc: redis_lib.Redis | None, user_id) -> str | None:
    """Return a human-readable reason to refuse a new call, or None to allow.

    Fails OPEN: if Redis is unreachable we allow the call. Blocking every call
    on a cache outage would be a worse failure than a temporarily uncapped spend
    that the duration caps still bound.
    """
    if rc is None:
        return None

    user_limit, platform_limit = _limits()
    try:
        used_user = int(rc.get(_user_key(user_id)) or 0)
        used_platform = int(rc.get(_platform_key()) or 0)
    except Exception as exc:
        log.warning("call budget check unavailable, allowing call: %s", exc)
        return None

    if used_platform >= platform_limit:
        log.error(
            "CALL BUDGET EXCEEDED: platform used %d/%d participant-minutes this "
            "month — refusing new calls",
            used_platform, platform_limit,
        )
        from app.core.monitoring import capture
        capture("Call budget exceeded — calling disabled platform-wide",
                level="error", used=used_platform, limit=platform_limit)
        return "Calling is temporarily unavailable."

    if used_user >= user_limit:
        log.warning(
            "call budget: user %s used %d/%d participant-minutes today",
            user_id, used_user, user_limit,
        )
        return "You have reached today's calling limit."

    return None


# ── Write ─────────────────────────────────────────────────────────────────────

def record_usage(
    rc: redis_lib.Redis | None,
    user_ids: list,
    duration_seconds: int,
) -> None:
    """Bill a finished call against the per-user and platform counters.

    `participant_minutes = participants x minutes`, rounded UP, because Stream
    bills started minutes. Called once when a call terminalises — including from
    the reapers, so an abandoned call still counts against budget.

    Fails silent: losing a counter increment must never break call teardown.
    """
    if rc is None or duration_seconds <= 0 or not user_ids:
        return

    minutes = max(1, -(-duration_seconds // 60))   # ceil division
    participant_minutes = minutes * len(user_ids)

    try:
        pipe = rc.pipeline(transaction=False)
        for uid in user_ids:
            key = _user_key(uid)
            pipe.incrby(key, minutes)
            pipe.expire(key, _USER_KEY_TTL)
        pkey = _platform_key()
        pipe.incrby(pkey, participant_minutes)
        pipe.expire(pkey, _PLATFORM_KEY_TTL)
        results = pipe.execute()
    except Exception as exc:
        log.warning("call usage recording failed: %s", exc)
        return

    # The platform incrby result is the second-to-last entry (expire is last).
    try:
        total = int(results[-2])
    except (IndexError, ValueError, TypeError):
        return

    _, platform_limit = _limits()
    if total >= platform_limit * PLATFORM_WARN_RATIO:
        from app.core.monitoring import capture
        capture("Call budget nearing its monthly limit", level="warning",
                used=total, limit=platform_limit)
        log.warning(
            "call budget: platform at %d/%d participant-minutes (%.0f%% of "
            "monthly budget)",
            total, platform_limit, 100.0 * total / max(platform_limit, 1),
        )


def current_usage(rc: redis_lib.Redis | None, user_id) -> dict:
    """Read-only snapshot, for an admin/ops endpoint or a debug log."""
    if rc is None:
        return {}
    user_limit, platform_limit = _limits()
    try:
        return {
            "user_minutes_today": int(rc.get(_user_key(user_id)) or 0),
            "user_daily_limit": user_limit,
            "platform_minutes_this_month": int(rc.get(_platform_key()) or 0),
            "platform_monthly_limit": platform_limit,
        }
    except Exception:
        return {}
