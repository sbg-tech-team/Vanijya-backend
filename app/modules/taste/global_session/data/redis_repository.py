"""
Redis implementation of IGlobalSessionRepository.

Data layer — imports from domain/ and core/ only.

Redis key  : session:global:{profile_id}
TTL        : 86400s (1 day). Also explicitly cleared by nightly promotion job.
Persistence: RDB snapshots every 5 min. Up to 5 min of data may be lost on restart.

Hash field layout:
  commodity:{id}:pos     Float  accumulated positive taste (all modules combined)
  commodity:{id}:neg     Float  accumulated negative taste
  commodity:{id}:conf    Float  accumulated confidence
  commodity:{id}:cnt     Int    event count
  commodity:{id}:ts      Int    unix timestamp of last write

  location:{key}:pos     Float  placeholder — zero-weighted until activated
  quantity:{key}:pos     Float  placeholder — zero-weighted until activated

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


def _commodity_dim_keys(raw: dict[bytes, bytes]) -> set[str]:
    prefix = b"commodity:"
    keys: set[str] = set()
    for field in raw:
        if field.startswith(prefix):
            parts = field.decode().split(":")
            if len(parts) == 3:
                keys.add(parts[1])
    return keys


class RedisGlobalSessionRepository(IGlobalSessionRepository):

    def __init__(self, rc: redis.Redis) -> None:
        self._rc = rc

    def _key(self, profile_id: int) -> str:
        return f"session:global:{profile_id}"

    # ── Write ─────────────────────────────────────────────────────────────────

    def write_commodity_delta(
        self,
        profile_id: int,
        delta: dict[str, float],
    ) -> None:
        if not delta:
            return

        key = self._key(profile_id)
        now = int(time.time())
        pipe = self._rc.pipeline(transaction=False)

        for ckey, pos_d in delta.items():
            if pos_d <= 0:
                continue
            pipe.hincrbyfloat(key, f"commodity:{ckey}:pos", pos_d)
            pipe.hincrby(key, f"commodity:{ckey}:cnt", 1)
            pipe.hset(key, f"commodity:{ckey}:ts", now)

        pipe.hincrby(key, "_total_events", len(delta))
        pipe.hsetnx(key, "_day", _today_int())
        pipe.hset(key, "_last_synced_at", now)
        pipe.expire(key, GLOBAL_SESSION_TTL)
        pipe.execute()

    # ── Read ──────────────────────────────────────────────────────────────────

    def read_commodity_weights(self, profile_id: int) -> dict[str, float]:
        raw = self._rc.hgetall(self._key(profile_id)) or {}
        return self._decay_scores(raw)

    def read_commodity_score(
        self,
        profile_id: int,
        commodity_key: str,
    ) -> GlobalDimScore:
        raw = self._rc.hgetall(self._key(profile_id)) or {}
        base = f"commodity:{commodity_key}".encode()
        return GlobalDimScore(
            key=commodity_key,
            pos=_f(raw.get(base + b":pos")),
            neg=_f(raw.get(base + b":neg")),
            conf=_f(raw.get(base + b":conf")),
            cnt=_i(raw.get(base + b":cnt")),
            last_ts=_i(raw.get(base + b":ts")),
        )

    def read_all_commodity_data(
        self,
        profile_id: int,
    ) -> dict[str, dict[str, float]]:
        raw = self._rc.hgetall(self._key(profile_id)) or {}
        result: dict[str, dict[str, float]] = {}
        for ckey in _commodity_dim_keys(raw):
            base = f"commodity:{ckey}".encode()
            result[ckey] = {
                "pos":  _f(raw.get(base + b":pos")),
                "neg":  _f(raw.get(base + b":neg")),
                "conf": _f(raw.get(base + b":conf")),
                "cnt":  float(_i(raw.get(base + b":cnt"))),
            }
        return result

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def clear(self, profile_id: int) -> None:
        self._rc.delete(self._key(profile_id))

    def session_exists(self, profile_id: int) -> bool:
        return bool(self._rc.exists(self._key(profile_id)))

    # ── Internal ──────────────────────────────────────────────────────────────

    def _decay_scores(self, raw: dict[bytes, bytes]) -> dict[str, float]:
        if not raw:
            return {}
        now = time.time()
        scores: dict[str, float] = {}
        for ckey in _commodity_dim_keys(raw):
            base = f"commodity:{ckey}".encode()
            pos = _f(raw.get(base + b":pos"))
            neg = _f(raw.get(base + b":neg"))
            ts  = _i(raw.get(base + b":ts"))
            days = (now - ts) / 86400.0 if ts else 0.0
            decayed = pos * math.exp(-TASTE_DECAY_LAMBDA * days)
            net = decayed - (neg * 0.6)
            if net > 0:
                scores[ckey] = net
        return scores
