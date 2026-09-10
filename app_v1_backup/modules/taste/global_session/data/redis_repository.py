"""
Redis implementation of IGlobalSessionRepository.

Data layer — imports from domain/ and core/ only.

Redis key  : session:global:{profile_id}
TTL        : 86400s (1 day). Also explicitly cleared by nightly promotion job.
Persistence: RDB snapshots every 5 min. Up to 5 min of data may be lost on restart.

Hash field layout (dimension-type-generic):
  {dimension_type}:{key}:pos     Float  accumulated positive taste (all modules combined)
  {dimension_type}:{key}:neg     Float  accumulated negative taste
  {dimension_type}:{key}:conf    Float  accumulated confidence
  {dimension_type}:{key}:cnt     Int    event count
  {dimension_type}:{key}:ts      Int    unix timestamp of last write

  Active dimension_types: commodity, city, state.
  Scaffolded, no writer yet: trade_intent (see CROSS_PLATFORM_DIMS).
  Placeholder: quantity.

  _total_events          Int    total events pushed from all modules today
  _day                   Int    YYYYMMDD — written on first event of the day
  _last_synced_at        Int    unix timestamp of last module→global push
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone

import redis

from app.modules.taste.session_taste.domain.constants import (
    GLOBAL_SESSION_TTL,
    TASTE_DECAY_LAMBDA,
)
from app.modules.taste.global_session.domain.entities import GlobalDimScore
from app.modules.taste.global_session.domain.interfaces import IGlobalSessionRepository


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
    """Every distinct dimension_type prefix in this hash (excludes bookkeeping
    fields like _total_events/_day/_last_synced_at, which have < 3 parts)."""
    types: set[str] = set()
    for field in raw:
        parts = field.decode().split(":")
        if len(parts) == 3:
            types.add(parts[0])
    return types


class RedisGlobalSessionRepository(IGlobalSessionRepository):

    def __init__(self, rc: redis.Redis) -> None:
        self._rc = rc

    def _key(self, profile_id: int) -> str:
        return f"session:global:{profile_id}"

    # ── Write ─────────────────────────────────────────────────────────────────

    def write_dimension_delta(
        self,
        profile_id: int,
        dimension_type: str,
        delta: dict[str, dict[str, float]],
    ) -> None:
        if not delta:
            return

        key = self._key(profile_id)
        now = int(time.time())
        pipe = self._rc.pipeline(transaction=False)

        for dkey, vals in delta.items():
            pos_d  = vals.get("pos", 0.0)
            neg_d  = vals.get("neg", 0.0)
            conf_d = vals.get("conf", 0.0)
            if pos_d <= 0 and neg_d <= 0 and conf_d <= 0:
                continue
            if pos_d > 0:
                pipe.hincrbyfloat(key, f"{dimension_type}:{dkey}:pos", pos_d)
            if neg_d > 0:
                pipe.hincrbyfloat(key, f"{dimension_type}:{dkey}:neg", neg_d)
            if conf_d > 0:
                pipe.hincrbyfloat(key, f"{dimension_type}:{dkey}:conf", conf_d)
            pipe.hincrby(key, f"{dimension_type}:{dkey}:cnt", 1)
            pipe.hset(key, f"{dimension_type}:{dkey}:ts", now)

        pipe.hincrby(key, "_total_events", len(delta))
        pipe.hsetnx(key, "_day", _today_int())
        pipe.hset(key, "_last_synced_at", now)
        pipe.expire(key, GLOBAL_SESSION_TTL)
        pipe.execute()

    # ── Read ──────────────────────────────────────────────────────────────────

    def read_dimension_weights(self, profile_id: int, dimension_type: str) -> dict[str, float]:
        raw = self._rc.hgetall(self._key(profile_id)) or {}
        return self._decay_scores(raw, dimension_type)

    def read_dimension_score(
        self,
        profile_id: int,
        dimension_type: str,
        key: str,
    ) -> GlobalDimScore:
        raw = self._rc.hgetall(self._key(profile_id)) or {}
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
        self,
        profile_id: int,
    ) -> dict[str, dict[str, dict[str, float]]]:
        raw = self._rc.hgetall(self._key(profile_id)) or {}
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

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def clear(self, profile_id: int) -> None:
        self._rc.delete(self._key(profile_id))

    def session_exists(self, profile_id: int) -> bool:
        return bool(self._rc.exists(self._key(profile_id)))

    def scan_active_profile_ids(self) -> list[int]:
        ids: list[int] = []
        for key in self._rc.scan_iter(match="session:global:*", count=500):
            try:
                raw = key.decode() if isinstance(key, bytes) else key
                ids.append(int(raw.rsplit(":", 1)[-1]))
            except (ValueError, AttributeError):
                continue
        return ids

    # ── Internal ──────────────────────────────────────────────────────────────

    def _decay_scores(self, raw: dict[bytes, bytes], dimension_type: str) -> dict[str, float]:
        if not raw:
            return {}
        now = time.time()
        scores: dict[str, float] = {}
        for dkey in _dim_keys_for_type(raw, dimension_type):
            base = f"{dimension_type}:{dkey}".encode()
            pos = _f(raw.get(base + b":pos"))
            neg = _f(raw.get(base + b":neg"))
            ts  = _i(raw.get(base + b":ts"))
            days = (now - ts) / 86400.0 if ts else 0.0
            decayed = pos * math.exp(-TASTE_DECAY_LAMBDA * days)
            net = decayed - (neg * 0.6)
            if net > 0:
                scores[dkey] = net
        return scores
