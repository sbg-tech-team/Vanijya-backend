"""Redis-backed participant presence.

Heartbeats are a write per participant per interval — at scale that is a lot of
row churn on `call_participants` for data whose whole lifetime is ninety
seconds. Redis holds it instead, with the key's own TTL doing the expiry.

    calls:hb:{call_id}:{user_id}  ->  unix ts,  TTL = HEARTBEAT_TIMEOUT x 2

**Fail-safe, not fail-open.** If Redis is unreachable the sweep must do NOTHING
rather than conclude everybody is gone: reading "no keys" from a dead Redis is
indistinguishable from "every client vanished", and acting on it would end every
live call on the platform at once. `presence_available()` gates that, and the DB
column remains as the slow-path fallback so the other guardrails still apply.
"""
from __future__ import annotations

import logging
import time
from uuid import UUID

import redis as redis_lib

from app.modules.calling.domain.value_objects import HEARTBEAT_TIMEOUT_SECONDS

log = logging.getLogger(__name__)

_TTL = HEARTBEAT_TIMEOUT_SECONDS * 2


def _key(call_id: UUID, user_id: UUID) -> str:
    return f"calls:hb:{call_id}:{user_id}"


def touch(rc: redis_lib.Redis | None, call_id: UUID, user_id: UUID) -> bool:
    """Record one participant as alive. False if Redis did not accept it, in
    which case the caller falls back to the database column."""
    if rc is None:
        return False
    try:
        rc.setex(_key(call_id, user_id), _TTL, int(time.time()))
        return True
    except Exception as exc:
        log.warning("presence write failed for call %s: %s", call_id, exc)
        return False


def present_user_ids(
    rc: redis_lib.Redis | None, call_id: UUID, candidate_ids: list[UUID]
) -> set[UUID] | None:
    """Which of `candidate_ids` have pinged recently.

    Returns None when presence data is unavailable — the caller must then skip
    the sweep entirely rather than treat an empty result as "nobody is here".
    """
    if rc is None or not candidate_ids:
        return None
    try:
        pipe = rc.pipeline(transaction=False)
        for uid in candidate_ids:
            pipe.get(_key(call_id, uid))
        raw = pipe.execute()
    except Exception as exc:
        log.warning("presence read failed for call %s: %s", call_id, exc)
        return None

    cutoff = time.time() - HEARTBEAT_TIMEOUT_SECONDS
    out: set[UUID] = set()
    for uid, val in zip(candidate_ids, raw):
        if val is None:
            continue
        try:
            if float(val) >= cutoff:
                out.add(uid)
        except (TypeError, ValueError):
            continue
    return out


def presence_available(rc: redis_lib.Redis | None) -> bool:
    """True only if Redis answered. Gates every presence-driven sweep so a cache
    outage can never be read as a platform-wide hangup."""
    if rc is None:
        return False
    try:
        return bool(rc.ping())
    except Exception:
        return False


def clear(rc: redis_lib.Redis | None, call_id: UUID, user_ids: list[UUID]) -> None:
    """Drop a finished call's keys. They would expire on their own; this just
    keeps Redis tidy."""
    if rc is None or not user_ids:
        return
    try:
        rc.delete(*[_key(call_id, uid) for uid in user_ids])
    except Exception:
        # Keys carry a TTL, so a failure here self-heals; it still means Redis
        # is unhealthy, which the sweeps depend on.
        log.warning("could not clear presence keys for call %s", call_id)
