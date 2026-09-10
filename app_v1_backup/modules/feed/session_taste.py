"""
Session Taste Engine — Redis-backed ephemeral engagement tracking.

Redis key : session:{profile_id}:{session_id}
TTL       : 2 hours
"""
from __future__ import annotations

import json
from typing import Optional

import redis

from app.modules.feed.schemas import EngagementSignal

# ── Signal weights ────────────────────────────────────────────────────────────

ACTION_WEIGHTS: dict[str, int] = {
    "save": 5,
    "share": 4,
    "comment": 4,
    "like": 3,
    "connection_accept": 3,
    "dwell": 2,
    "strong_dwell": 2,   # +30 % bonus applied separately via avg_dwell check
    "skip": -1,
    "connection_dismiss": -1,
}

# ── Default weights (cold-start) ──────────────────────────────────────────────

PAGE_LEVEL_DEFAULTS: dict[int, dict[str, float]] = {
    1: {"post": 0.50, "news": 0.25, "group": 0.15, "connection": 0.10},
    2: {"post": 0.50, "news": 0.25, "group": 0.15, "connection": 0.10},
    3: {"post": 0.55, "news": 0.15, "group": 0.20, "connection": 0.10},
    4: {"post": 0.55, "news": 0.15, "group": 0.20, "connection": 0.10},
    5: {"post": 0.55, "news": 0.15, "group": 0.20, "connection": 0.10},
}
PAGE_LEVEL_DEEP = {"post": 0.65, "news": 0.05, "group": 0.15, "connection": 0.15}

CONTENT_TYPES = ["post", "news", "group", "connection"]

SESSION_TTL = 7200  # 2 hours


def _session_key(profile_id: int, session_id: str) -> str:
    return f"session:{profile_id}:{session_id}"


# ── Read / Write ──────────────────────────────────────────────────────────────

def get_session_taste(
    rc: redis.Redis,
    profile_id: int,
    session_id: str,
) -> dict:
    raw = rc.get(_session_key(profile_id, session_id))
    if raw:
        return json.loads(raw)
    return _empty_taste()


def update_session_taste(
    rc: redis.Redis,
    profile_id: int,
    session_id: str,
    signals: list[EngagementSignal],
) -> None:
    key = _session_key(profile_id, session_id)
    taste = get_session_taste(rc, profile_id, session_id)

    for sig in signals:
        ct = sig.item_type
        if ct not in taste:
            taste[ct] = _empty_type_block(ct)

        block = taste[ct]
        action = sig.action
        weight = ACTION_WEIGHTS.get(action, 0)

        if action in ("dwell", "strong_dwell"):
            block["dwells"] = block.get("dwells", 0) + 1
            if sig.dwell_ms:
                block["total_dwell_ms"] = block.get("total_dwell_ms", 0) + sig.dwell_ms
        elif action == "skip":
            block["skips"] = block.get("skips", 0) + 1
        elif action == "like":
            block["likes"] = block.get("likes", 0) + 1
        elif action == "save":
            block["saves"] = block.get("saves", 0) + 1
        elif action in ("share", "comment"):
            block["shares"] = block.get("shares", 0) + (1 if action == "share" else 0)
            block["comments"] = block.get("comments", 0) + (1 if action == "comment" else 0)
        elif action == "connection_accept":
            block["accepts"] = block.get("accepts", 0) + 1
        elif action == "connection_dismiss":
            block["dismisses"] = block.get("dismisses", 0) + 1

        taste[ct] = block

    taste["items_seen"] = taste.get("items_seen", 0) + len(signals)

    rc.set(key, json.dumps(taste), ex=SESSION_TTL)


# ── Weight computation ────────────────────────────────────────────────────────

def compute_weights(
    taste: dict,
    page_num: int,
) -> dict[str, float]:
    """Blend page-level defaults with session-observed weights."""
    items_seen = taste.get("items_seen", 0)
    blend_factor = _blend_factor(items_seen)

    page_defaults = PAGE_LEVEL_DEFAULTS.get(page_num, PAGE_LEVEL_DEEP)

    if blend_factor == 0.0:
        return dict(page_defaults)

    observed = _observed_weights(taste)

    final: dict[str, float] = {}
    for ct in CONTENT_TYPES:
        final[ct] = blend_factor * observed[ct] + (1 - blend_factor) * page_defaults[ct]

    # Normalise so they sum to 1.0
    total = sum(final.values())
    return {ct: v / total for ct, v in final.items()}


def _blend_factor(items_seen: int) -> float:
    if items_seen < 8:
        return 0.0
    return min(0.8, 0.1 + (items_seen - 8) * 0.025)


def _observed_weights(taste: dict) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ct in CONTENT_TYPES:
        block = taste.get(ct, {})
        saves = block.get("saves", 0)
        likes = block.get("likes", 0)
        dwells = block.get("dwells", 0)
        skips = block.get("skips", 0)
        total_dwell_ms = block.get("total_dwell_ms", 0)
        items_of_type = max(dwells + skips, 1)

        score = saves * 5 + likes * 3 + dwells * 2 - skips * 1
        avg_dwell = total_dwell_ms / items_of_type
        if avg_dwell > 6000:
            score *= 1.3
        score = max(score, 0.1)
        scores[ct] = score

    total = sum(scores.values())
    return {ct: s / total for ct, s in scores.items()}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _empty_taste() -> dict:
    return {
        "post": _empty_type_block("post"),
        "news": _empty_type_block("news"),
        "group": _empty_type_block("group"),
        "connection": _empty_type_block("connection"),
        "items_seen": 0,
    }


def _empty_type_block(ct: str) -> dict:
    if ct == "connection":
        return {"dwells": 0, "accepts": 0, "dismisses": 0}
    return {"dwells": 0, "likes": 0, "saves": 0, "skips": 0, "total_dwell_ms": 0}
