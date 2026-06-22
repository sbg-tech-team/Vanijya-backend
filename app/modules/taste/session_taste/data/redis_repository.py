"""
Redis implementation of IModuleSessionRepository.

Data layer — imports from domain/ and core/ only.
No business logic; all weight/threshold decisions live in domain/constants.py.

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

dim prefix mapping:  category→cat  commodity→com  author→aut
"""
from __future__ import annotations

import math
import time

import redis

from app.modules.taste.session_taste.domain.constants import (
    MODULE_SESSION_TTL,
    SIGNAL_WEIGHTS,
    TASTE_DECAY_LAMBDA,
)
from app.modules.taste.session_taste.domain.entities import DimScore, SessionSignal
from app.modules.taste.session_taste.domain.interfaces import IModuleSessionRepository


_DIM_PREFIX: dict[str, str] = {
    "category":  "cat",
    "commodity": "com",
    "author":    "aut",
    "role":      "rol",
}


def _pfx(dimension_type: str) -> str:
    return _DIM_PREFIX.get(dimension_type, dimension_type[:3])


def _f(val: bytes | str | None) -> float:
    """Decode bytes/str → float. decode_responses=False means raw bytes."""
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


class RedisModuleSessionRepository(IModuleSessionRepository):

    def __init__(self, rc: redis.Redis) -> None:
        self._rc = rc

    def _key(self, module: str, profile_id: int) -> str:
        return f"session:{module}:{profile_id}"

    # ── Write ─────────────────────────────────────────────────────────────────

    def write_signals(
        self,
        profile_id: int,
        module: str,
        signals: list[SessionSignal],
    ) -> None:
        if not signals:
            return

        key = self._key(module, profile_id)
        now = int(time.time())
        pipe = self._rc.pipeline(transaction=False)

        for sig in signals:
            pos_d, neg_d, conf_d = SIGNAL_WEIGHTS.get(sig.action, (0.0, 0.0, 0.0))
            if not (pos_d or neg_d or conf_d):
                continue

            base = f"{_pfx(sig.dimension_type)}:{sig.dimension_key}"
            if pos_d > 0:
                pipe.hincrbyfloat(key, f"{base}:pos", pos_d)
            if neg_d > 0:
                pipe.hincrbyfloat(key, f"{base}:neg", neg_d)
            if conf_d > 0:
                pipe.hincrbyfloat(key, f"{base}:conf", conf_d)
            pipe.hincrby(key, f"{base}:cnt", 1)
            pipe.hset(key, f"{base}:ts", sig.occurred_at_unix)

        pipe.hincrby(key, "_total_events", len(signals))
        pipe.hsetnx(key, "_session_start", now)
        pipe.hset(key, "_last_event_at", now)
        pipe.expire(key, MODULE_SESSION_TTL)
        pipe.execute()

    # ── Read ──────────────────────────────────────────────────────────────────

    def read_dimension_scores(
        self,
        profile_id: int,
        module: str,
        dimension_type: str,
    ) -> dict[str, float]:
        raw = self._rc.hgetall(self._key(module, profile_id)) or {}
        return self._scores_from_raw(raw, dimension_type)

    def read_dim_score(
        self,
        profile_id: int,
        module: str,
        dimension_type: str,
        key: str,
    ) -> DimScore:
        raw = self._rc.hgetall(self._key(module, profile_id)) or {}
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

    # ── Commodity sync delta ──────────────────────────────────────────────────

    def get_commodity_delta_and_snapshot(
        self,
        profile_id: int,
        module: str,
    ) -> tuple[dict[str, float], dict[str, float]]:
        raw = self._rc.hgetall(self._key(module, profile_id)) or {}
        if not raw:
            return {}, {}

        dim_keys = self._dim_keys_from_raw(raw, "com:")
        delta: dict[str, float] = {}
        snapshot: dict[str, float] = {}

        for dkey in dim_keys:
            pos    = _f(raw.get(f"com:{dkey}:pos".encode()))
            synced = _f(raw.get(f"com:{dkey}:synced".encode()))
            diff   = pos - synced
            snapshot[dkey] = pos
            if diff > 0.01:
                delta[dkey] = diff

        return delta, snapshot

    def mark_synced(
        self,
        profile_id: int,
        module: str,
        snapshot: dict[str, float],
    ) -> None:
        if not snapshot:
            return
        key = self._key(module, profile_id)
        now = int(time.time())
        pipe = self._rc.pipeline(transaction=False)
        for dkey, pos_val in snapshot.items():
            pipe.hset(key, f"com:{dkey}:synced", pos_val)
        pipe.hset(key, "_last_synced_ts", now)
        pipe.execute()

    def session_exists(self, profile_id: int, module: str) -> bool:
        return bool(self._rc.exists(self._key(module, profile_id)))

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _scores_from_raw(
        self,
        raw: dict[bytes, bytes],
        dimension_type: str,
    ) -> dict[str, float]:
        if not raw:
            return {}

        pfx = _pfx(dimension_type)
        prefix = f"{pfx}:".encode()
        now = time.time()

        dim_keys = self._dim_keys_from_raw(raw, prefix.decode())
        scores: dict[str, float] = {}

        for dkey in dim_keys:
            base = f"{pfx}:{dkey}".encode()
            pos = _f(raw.get(base + b":pos"))
            neg = _f(raw.get(base + b":neg"))
            ts  = _i(raw.get(base + b":ts"))

            days = (now - ts) / 86400.0 if ts else 0.0
            decayed = pos * math.exp(-TASTE_DECAY_LAMBDA * days)
            net = decayed - (neg * 0.6)
            if net > 0:
                scores[dkey] = net

        return scores

    @staticmethod
    def _dim_keys_from_raw(
        raw: dict[bytes, bytes],
        prefix: str,
    ) -> set[str]:
        prefix_bytes = prefix.encode() if isinstance(prefix, str) else prefix
        dim_keys: set[str] = set()
        for field in raw:
            if field.startswith(prefix_bytes):
                parts = field.decode().split(":")
                if len(parts) == 3:
                    dim_keys.add(parts[1])
        return dim_keys
