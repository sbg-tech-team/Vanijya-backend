"""
Module session taste service — Redis-backed per-module session store.

Redis key  : session:{module}:{profile_id}   e.g. session:post:42
TTL        : 2 h inactivity (EXPIRE resets on every write_signals call)
Persistence: none — module session loss on restart is acceptable

Hash field layout:
  {pfx}:{dim_key}:pos      Float  accumulated positive taste
  {pfx}:{dim_key}:neg      Float  accumulated negative taste
  {pfx}:{dim_key}:conf     Float  accumulated confidence
  {pfx}:{dim_key}:cnt      Int    event count
  {pfx}:{dim_key}:ts       Int    unix timestamp of last event
  {pfx}:{dim_key}:synced   Float  pos snapshot at last global sync

  _total_events            Int    total events across all dimensions
  _session_start           Int    unix timestamp when session was first created
  _last_event_at           Int    unix timestamp of most recent event
  _last_synced_ts          Int    unix timestamp of last module→global sync

dim prefix mapping:  category→cat  commodity→com  author→aut  role→rol
                     city→cit  state→sta  trade_intent→tin
"""
from __future__ import annotations

import time

import redis

from app.recommendation.session_taste.constants import (
    MODULE_SESSION_TTL,
    SIGNAL_WEIGHTS,
    TASTE_DECAY_LAMBDA,
)
from app.recommendation.session_taste.schemas import DimScore, SessionSignal
from app.shared.utils.time_decay import decayed_score


_DIM_PREFIX: dict[str, str] = {
    "category":     "cat",
    "commodity":    "com",
    "author":       "aut",
    "role":         "rol",
    "city":         "cit",
    "state":        "sta",
    "trade_intent": "tin",
}


def _pfx(dimension_type: str) -> str:
    return _DIM_PREFIX.get(dimension_type, dimension_type[:3])


def _key(module: str, profile_id: int) -> str:
    return f"session:{module}:{profile_id}"


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


def _dim_keys_from_raw(raw: dict[bytes, bytes], prefix: str) -> set[str]:
    prefix_bytes = prefix.encode() if isinstance(prefix, str) else prefix
    dim_keys: set[str] = set()
    for field in raw:
        if field.startswith(prefix_bytes):
            parts = field.decode().split(":")
            if len(parts) == 3:
                dim_keys.add(parts[1])
    return dim_keys


# ── Write ─────────────────────────────────────────────────────────────────────

def write_signals(
    rc: redis.Redis,
    profile_id: int,
    module: str,
    signals: list[SessionSignal],
) -> None:
    """Ingest a batch of interaction signals into the module session store."""
    if not signals:
        return

    rkey = _key(module, profile_id)
    now = int(time.time())
    pipe = rc.pipeline(transaction=False)

    for sig in signals:
        pos_d, neg_d, conf_d = SIGNAL_WEIGHTS.get(sig.action, (0.0, 0.0, 0.0))
        if not (pos_d or neg_d or conf_d):
            continue

        base = f"{_pfx(sig.dimension_type)}:{sig.dimension_key}"
        if pos_d > 0:
            pipe.hincrbyfloat(rkey, f"{base}:pos", pos_d)
        if neg_d > 0:
            pipe.hincrbyfloat(rkey, f"{base}:neg", neg_d)
        if conf_d > 0:
            pipe.hincrbyfloat(rkey, f"{base}:conf", conf_d)
        pipe.hincrby(rkey, f"{base}:cnt", 1)
        pipe.hset(rkey, f"{base}:ts", sig.occurred_at_unix)

    pipe.hincrby(rkey, "_total_events", len(signals))
    pipe.hsetnx(rkey, "_session_start", now)
    pipe.hset(rkey, "_last_event_at", now)
    pipe.expire(rkey, MODULE_SESSION_TTL)
    pipe.execute()


# ── Read ──────────────────────────────────────────────────────────────────────

def read_dimension_scores(
    rc: redis.Redis,
    profile_id: int,
    module: str,
    dimension_type: str,
) -> dict[str, float]:
    """Return decay-adjusted net scores for every key in one dimension."""
    raw = rc.hgetall(_key(module, profile_id)) or {}
    if not raw:
        return {}

    pfx = _pfx(dimension_type)
    prefix = f"{pfx}:".encode()

    dim_keys = _dim_keys_from_raw(raw, prefix.decode())
    scores: dict[str, float] = {}

    for dkey in dim_keys:
        base = f"{pfx}:{dkey}".encode()
        pos = _f(raw.get(base + b":pos"))
        neg = _f(raw.get(base + b":neg"))
        ts  = _i(raw.get(base + b":ts"))

        net = decayed_score(pos, neg, ts or None, TASTE_DECAY_LAMBDA)
        if net > 0:
            scores[dkey] = net

    return scores


def read_dim_score(
    rc: redis.Redis,
    profile_id: int,
    module: str,
    dimension_type: str,
    key: str,
) -> DimScore:
    """Return the full score record for one specific dimension key."""
    raw = rc.hgetall(_key(module, profile_id)) or {}
    pfx = _pfx(dimension_type)
    base = f"{pfx}:{key}".encode()
    return DimScore(
        key=key,
        pos=_f(raw.get(base + b":pos")),
        neg=_f(raw.get(base + b":neg")),
        conf=_f(raw.get(base + b":conf")),
        cnt=_i(raw.get(base + b":cnt")),
        last_ts=_i(raw.get(base + b":ts")),
    )


def read_dimension_weights(
    rc: redis.Redis,
    profile_id: int,
    module: str,
    dimension_type: str,
) -> dict[str, float]:
    """
    Decay-adjusted net weights for one dimension.
    Returns empty dict when no session exists.
    """
    if not session_exists(rc, profile_id, module):
        return {}
    return read_dimension_scores(rc, profile_id, module, dimension_type)


# ── Cross-platform dimension sync ─────────────────────────────────────────────

def get_dimension_delta_and_snapshot(
    rc: redis.Redis,
    profile_id: int,
    module: str,
    dimension_type: str,
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    """
    Compute the unsynced delta (pos/neg/conf, independently) for one
    cross-platform dimension since the last global sync.

    Returns (delta, snapshot) where each value is {key: {"pos":.., "neg":.., "conf":..}}.
    Caller writes delta to global session, then passes snapshot to
    mark_dimension_synced to prevent double-counting on the next call.
    """
    raw = rc.hgetall(_key(module, profile_id)) or {}
    if not raw:
        return {}, {}

    pfx = _pfx(dimension_type)
    dim_keys = _dim_keys_from_raw(raw, f"{pfx}:")
    delta: dict[str, dict[str, float]] = {}
    snapshot: dict[str, dict[str, float]] = {}

    for dkey in dim_keys:
        pos         = _f(raw.get(f"{pfx}:{dkey}:pos".encode()))
        neg         = _f(raw.get(f"{pfx}:{dkey}:neg".encode()))
        conf        = _f(raw.get(f"{pfx}:{dkey}:conf".encode()))
        pos_synced  = _f(raw.get(f"{pfx}:{dkey}:synced".encode()))
        neg_synced  = _f(raw.get(f"{pfx}:{dkey}:neg_synced".encode()))
        conf_synced = _f(raw.get(f"{pfx}:{dkey}:conf_synced".encode()))

        pos_d  = max(pos - pos_synced, 0.0)
        neg_d  = max(neg - neg_synced, 0.0)
        conf_d = max(conf - conf_synced, 0.0)

        snapshot[dkey] = {"pos": pos, "neg": neg, "conf": conf}
        if pos_d > 0.01 or neg_d > 0.01 or conf_d > 0.01:
            delta[dkey] = {"pos": pos_d, "neg": neg_d, "conf": conf_d}

    return delta, snapshot


def mark_dimension_synced(
    rc: redis.Redis,
    profile_id: int,
    module: str,
    dimension_type: str,
    snapshot: dict[str, dict[str, float]],
) -> None:
    """
    Record the synced pos/neg/conf snapshot so the next
    get_dimension_delta_and_snapshot call only returns the increment that
    happened after this call.
    Called ONLY after a successful global session write.
    """
    if not snapshot:
        return
    rkey = _key(module, profile_id)
    pfx = _pfx(dimension_type)
    now = int(time.time())
    pipe = rc.pipeline(transaction=False)
    for dkey, vals in snapshot.items():
        pipe.hset(rkey, f"{pfx}:{dkey}:synced", vals.get("pos", 0.0))
        pipe.hset(rkey, f"{pfx}:{dkey}:neg_synced", vals.get("neg", 0.0))
        pipe.hset(rkey, f"{pfx}:{dkey}:conf_synced", vals.get("conf", 0.0))
    pipe.hset(rkey, "_last_synced_ts", now)
    pipe.execute()


# ── Lifecycle ─────────────────────────────────────────────────────────────────

def session_exists(rc: redis.Redis, profile_id: int, module: str) -> bool:
    """Return True if a live session hash exists in Redis."""
    return bool(rc.exists(_key(module, profile_id)))
