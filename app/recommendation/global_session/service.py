"""
Global session service — Redis-backed cross-module dimension aggregation.

Redis key  : session:global:{profile_id}
TTL        : 86400s (1 day). Also explicitly cleared by nightly promotion job.
Persistence: RDB snapshots every 5 min. Up to 5 min of data may be lost on restart.

Hash field layout — dimension-type-generic:
  {dimension_type}:{key}:pos     Float  accumulated positive taste (all modules combined)
  {dimension_type}:{key}:neg     Float  accumulated negative taste
  {dimension_type}:{key}:conf    Float  accumulated confidence
  {dimension_type}:{key}:cnt     Int    event count
  {dimension_type}:{key}:ts      Int    unix timestamp of last write

  Active dimension_types: commodity, city, state.
  Scaffolded, no writer yet: trade_intent.
  Placeholder: quantity.

  _total_events          Int    total events pushed from all modules today
  _day                   Int    YYYYMMDD — written on first event of the day
  _last_synced_at        Int    unix timestamp of last module→global push
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import redis

from app.recommendation.session_taste.constants import (
    GLOBAL_SESSION_TTL,
    TASTE_DECAY_LAMBDA,
)
from app.recommendation.global_session.schemas import GlobalDimScore
from app.shared.utils.time_decay import decayed_score


def _key(profile_id: int) -> str:
    return f"session:global:{profile_id}"


def _f(val: bytes | str | None) -> float:
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _i(val: bytes | str | None) -> int:
    if val is None:
        return 0
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0


def _today_int() -> int:
    d = datetime.now(timezone.utc)
    return d.year * 10000 + d.month * 100 + d.day


def _dim_keys_for_type(raw: dict[bytes, bytes], dimension_type: str) -> set[str]:
    prefix = f"{dimension_type}:".encode()
    keys: set[str] = set()
    for field in raw:
        if field.startswith(prefix):
            parts = field.decode().split(":")
            if len(parts) == 3:
                keys.add(parts[1])
    return keys


def _dimension_types_present(raw: dict[bytes, bytes]) -> set[str]:
    """Every distinct dimension_type with at least one {type}:{key}:{suffix} field."""
    types: set[str] = set()
    for field in raw:
        parts = field.decode().split(":") if isinstance(field, bytes) else field.split(":")
        if len(parts) == 3:
            types.add(parts[0])
    return types


def _decay_scores(raw: dict[bytes, bytes], dimension_type: str) -> dict[str, float]:
    if not raw:
        return {}
    scores: dict[str, float] = {}
    for dkey in _dim_keys_for_type(raw, dimension_type):
        base = f"{dimension_type}:{dkey}".encode()
        pos = _f(raw.get(base + b":pos"))
        neg = _f(raw.get(base + b":neg"))
        ts  = _i(raw.get(base + b":ts"))
        net = decayed_score(pos, neg, ts or None, TASTE_DECAY_LAMBDA)
        if net > 0:
            scores[dkey] = net
    return scores


# ── Write ─────────────────────────────────────────────────────────────────────

def write_dimension_delta(
    rc: redis.Redis,
    profile_id: int,
    dimension_type: str,
    delta: dict[str, dict[str, float]],
) -> None:
    """
    Atomically add pos/neg/conf deltas from one module sync, for one dimension.

    `delta` is {key: {"pos": .., "neg": .., "conf": ..}} as produced by
    app.recommendation.session_taste.service.get_dimension_delta_and_snapshot.
    """
    if not delta:
        return

    rkey = _key(profile_id)
    now = int(time.time())
    pipe = rc.pipeline(transaction=False)

    for dkey, vals in delta.items():
        pos_d  = vals.get("pos", 0.0)
        neg_d  = vals.get("neg", 0.0)
        conf_d = vals.get("conf", 0.0)
        if pos_d <= 0 and neg_d <= 0 and conf_d <= 0:
            continue
        if pos_d > 0:
            pipe.hincrbyfloat(rkey, f"{dimension_type}:{dkey}:pos", pos_d)
        if neg_d > 0:
            pipe.hincrbyfloat(rkey, f"{dimension_type}:{dkey}:neg", neg_d)
        if conf_d > 0:
            pipe.hincrbyfloat(rkey, f"{dimension_type}:{dkey}:conf", conf_d)
        pipe.hincrby(rkey, f"{dimension_type}:{dkey}:cnt", 1)
        pipe.hset(rkey, f"{dimension_type}:{dkey}:ts", now)

    pipe.hincrby(rkey, "_total_events", len(delta))
    pipe.hsetnx(rkey, "_day", _today_int())
    pipe.hset(rkey, "_last_synced_at", now)
    pipe.expire(rkey, GLOBAL_SESSION_TTL)
    pipe.execute()


# ── Read ──────────────────────────────────────────────────────────────────────

def read_dimension_weights(rc: redis.Redis, profile_id: int, dimension_type: str) -> dict[str, float]:
    """Return decay-adjusted net scores for all keys of one dimension."""
    raw = rc.hgetall(_key(profile_id)) or {}
    return _decay_scores(raw, dimension_type)


def read_dimension_score(
    rc: redis.Redis,
    profile_id: int,
    dimension_type: str,
    key: str,
) -> GlobalDimScore:
    """Return the full score record for one dimension key."""
    raw = rc.hgetall(_key(profile_id)) or {}
    base = f"{dimension_type}:{key}".encode()
    return GlobalDimScore(
        key=key,
        pos=_f(raw.get(base + b":pos")),
        neg=_f(raw.get(base + b":neg")),
        conf=_f(raw.get(base + b":conf")),
        cnt=_i(raw.get(base + b":cnt")),
        last_ts=_i(raw.get(base + b":ts")),
    )


def read_all_dimension_data(
    rc: redis.Redis,
    profile_id: int,
) -> dict[str, dict[str, dict[str, float]]]:
    """
    Return raw {dimension_type: {key: {pos, neg, conf, cnt}}} for the nightly
    promotion job. No decay applied — job needs raw values.
    """
    raw = rc.hgetall(_key(profile_id)) or {}
    result: dict[str, dict[str, dict[str, float]]] = {}
    for dim_type in _dimension_types_present(raw):
        dim_result: dict[str, dict[str, float]] = {}
        for dkey in _dim_keys_for_type(raw, dim_type):
            base = f"{dim_type}:{dkey}".encode()
            dim_result[dkey] = {
                "pos":  _f(raw.get(base + b":pos")),
                "neg":  _f(raw.get(base + b":neg")),
                "conf": _f(raw.get(base + b":conf")),
                "cnt":  float(_i(raw.get(base + b":cnt"))),
            }
        result[dim_type] = dim_result
    return result


# ── Lifecycle ─────────────────────────────────────────────────────────────────

def clear(rc: redis.Redis, profile_id: int) -> None:
    """Delete the global session after successful nightly promotion."""
    rc.delete(_key(profile_id))


def session_exists(rc: redis.Redis, profile_id: int) -> bool:
    """Return True if a live global session hash exists."""
    return bool(rc.exists(_key(profile_id)))


def list_active_profile_ids(rc: redis.Redis) -> list[int]:
    """
    Return all profile IDs that currently have an active global session.
    Used by the nightly promotion job to discover which profiles to process.
    """
    profile_ids: list[int] = []
    cursor = 0
    while True:
        cursor, keys = rc.scan(cursor, match="session:global:*", count=100)
        for raw_key in keys:
            key_str = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
            parts = key_str.split(":")
            if len(parts) == 3:
                try:
                    profile_ids.append(int(parts[2]))
                except ValueError:
                    pass
        if cursor == 0:
            break
    return profile_ids
