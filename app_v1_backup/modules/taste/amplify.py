"""
Amplify glue — shared read-side helpers for module recommendation engines.

Mechanism 1 (Amplify): re-rank an existing candidate pool using blended taste.
This module wraps the lower-level taste APIs so a caller (connections, groups,
…) makes ONE call to get blended commodity weights, and ONE call to turn a
candidate's commodities into a score multiplier.

Read-time sequence encapsulated by get_amplify_weights:
    1. persistent  = read_global_taste_weights(db, pid, dim)      # Layer 3 (DB)
    2. sync_module_to_global(rc, pid, module)                     # push Layer 1 → Layer 2
    3. merge_weights(rc, pid, module, dim, persistent)           # blend all 3 layers

Every taste call is wrapped so a Redis outage or a missing user_global_taste
table can never break a recommendation — the caller silently degrades to a
weaker (or no) boost.

NOTE: dimension_key for commodity is the DB commodity_id as a string ("1"=rice,
"2"=cotton, "3"=sugar). Candidate profiles / groups carry commodity *names*, so
callers must map name → id via commodity_id_by_name(db) before boosting.
"""
from __future__ import annotations

import time

import redis as _redis
from sqlalchemy.orm import Session

from app.modules.taste.global_session import merge_weights, sync_module_to_global
from app.modules.taste.global_taste import read_global_taste_weights
from app.modules.taste.session_taste import ActionType, SessionSignal, write_signals

# ── Tunables ───────────────────────────────────────────────────────────────────
# BOOST_MAX  — the strongest multiplier a fully session-hot commodity can add.
#              1.0 + 0.30 = 1.30× at saturation.
# BOOST_REF  — merged-weight at which a commodity reaches full boost. Lower =
#              a single strong action (follow/join) moves the needle more.
# Both are knobs; tune against real behaviour, the architecture doesn't change.
BOOST_MAX: float = 0.30
BOOST_REF: float = 3.0


# ── Commodity id ⇆ name map (source of truth: commodities table) ───────────────
# Cached process-wide — the commodity set is tiny and effectively static.
_commodity_id_by_name: dict[str, int] | None = None


def commodity_id_by_name(db: Session) -> dict[str, int]:
    """Return {lowercase_commodity_name: commodity_id}, loaded once from the DB."""
    global _commodity_id_by_name
    if _commodity_id_by_name is None:
        from app.modules.profile.models import Commodity
        rows = db.query(Commodity).all()
        _commodity_id_by_name = {r.name.lower(): r.id for r in rows}
    return _commodity_id_by_name


def commodity_ids_for(db: Session, commodity_names: list[str]) -> list[int]:
    """Map a list of commodity names → ids, dropping anything unknown."""
    lut = commodity_id_by_name(db)
    return [lut[n.lower()] for n in commodity_names if n.lower() in lut]


# ── Write-side helper ──────────────────────────────────────────────────────────

def write_commodity_signals(
    rc: _redis.Redis | None,
    profile_id: int,
    module: str,
    commodity_ids: list[int],
    action: ActionType,
    role_id: int | None = None,
) -> None:
    """
    Fire-and-forget: record an interaction's commodity (+ optional role) into the
    module session hash. Fully fails silent — a Redis outage must never break the
    calling action (follow / msg / join / view).

    role is recorded to the module session but is NOT yet used by the boost.
    """
    if rc is None or not commodity_ids:
        return
    try:
        now = int(time.time())
        signals = [
            SessionSignal(
                dimension_type="commodity",
                dimension_key=str(cid),
                action=action,
                occurred_at_unix=now,
            )
            for cid in commodity_ids
        ]
        if role_id is not None:
            signals.append(
                SessionSignal(
                    dimension_type="role",
                    dimension_key=str(role_id),
                    action=action,
                    occurred_at_unix=now,
                )
            )
        write_signals(rc, profile_id, module, signals)
    except Exception:
        pass


def write_post_signals(
    rc: _redis.Redis | None,
    profile_id: int,
    category: str,
    commodity_id: int | None,
    action: ActionType,
    city: str | None = None,
    state: str | None = None,
) -> None:
    """
    Fire-and-forget: record one Post interaction's category + commodity (+
    city/state, from the post author's Business record) into
    session:post:{profile_id}.

    Author dimension is intentionally NOT written here (deferred) — add it by
    following the same gate already used in
    post_user_interaction/service.py's record_interaction:
    pos_delta >= AUTHOR_MIN_TASTE_DELTA and author_profile_id != profile_id.
    """
    if rc is None:
        return
    try:
        now = int(time.time())
        signals = [
            SessionSignal(
                dimension_type="category",
                dimension_key=category,
                action=action,
                occurred_at_unix=now,
            )
        ]
        if commodity_id is not None:
            signals.append(
                SessionSignal(
                    dimension_type="commodity",
                    dimension_key=str(commodity_id),
                    action=action,
                    occurred_at_unix=now,
                )
            )
        if city:
            signals.append(
                SessionSignal(
                    dimension_type="city",
                    dimension_key=city.strip().lower(),
                    action=action,
                    occurred_at_unix=now,
                )
            )
        if state:
            signals.append(
                SessionSignal(
                    dimension_type="state",
                    dimension_key=state.strip().lower(),
                    action=action,
                    occurred_at_unix=now,
                )
            )
        write_signals(rc, profile_id, "post", signals)
    except Exception:
        pass


def write_news_signals(
    rc: _redis.Redis | None,
    profile_id: int,
    commodity_ids: list[int],
    location_city: str | None,
    location_state: str | None,
    action: ActionType,
) -> None:
    """
    Fire-and-forget: record one News interaction's commodity + city + state
    into session:news:{profile_id}.

    city/state are now full cross-platform dimensions (3-layer, global-synced)
    -- superseding the earlier News-local 2-layer "location" dimension.
    location_city/location_state come directly from EnrichedArticle's LLM-
    extracted fields (the single primary place the story is about), not from
    the older state_tags list.
    """
    if rc is None:
        return
    try:
        now = int(time.time())
        signals = [
            SessionSignal(
                dimension_type="commodity",
                dimension_key=str(cid),
                action=action,
                occurred_at_unix=now,
            )
            for cid in commodity_ids
        ]
        if location_city:
            signals.append(
                SessionSignal(
                    dimension_type="city",
                    dimension_key=location_city.strip().lower(),
                    action=action,
                    occurred_at_unix=now,
                )
            )
        if location_state:
            signals.append(
                SessionSignal(
                    dimension_type="state",
                    dimension_key=location_state.strip().lower(),
                    action=action,
                    occurred_at_unix=now,
                )
            )
        if signals:
            write_signals(rc, profile_id, "news", signals)
    except Exception:
        pass


# ── Read-side orchestration ────────────────────────────────────────────────────

def get_amplify_weights(
    db: Session,
    rc: _redis.Redis,
    profile_id: int,
    module: str,
    dimension_type: str = "commodity",
) -> dict[str, float]:
    """
    Blend persistent (DB) + module session + global session into one weight dict
    keyed by dimension_key (commodity_id as string).

    Cold start (no session yet) → returns pure persistent weights.
    Fully fails safe → returns {} if every layer is unavailable.
    """
    # Layer 3 — persistent (table may not exist yet; empty on any failure)
    try:
        persistent = read_global_taste_weights(db, profile_id, dimension_type)
    except Exception:
        persistent = {}

    # Layer 1 → Layer 2 — push this module's unsynced commodity delta to global
    try:
        sync_module_to_global(rc, profile_id, module)
    except Exception:
        pass

    # Blend all three layers (confidence-gated inside merge_weights)
    try:
        return merge_weights(rc, profile_id, module, dimension_type, persistent)
    except Exception:
        return persistent


# ── Boost calculation ──────────────────────────────────────────────────────────

def _hottest_boost(
    weights: dict[str, float],
    candidate_keys: list[str],
    boost_max: float,
    ref: float,
) -> float:
    """
    Score multiplier in [1.0, 1.0 + boost_max] for a single candidate.

    Takes the candidate's HOTTEST matching key (max, not sum) so a
    many-key candidate can't auto-outrank a focused one. Returns 1.0
    (no-op) when there's no session/persistent signal for its keys.
    """
    if not weights or not candidate_keys:
        return 1.0

    best = 0.0
    for key in candidate_keys:
        w = weights.get(key, 0.0)
        if w > best:
            best = w

    if best <= 0.0:
        return 1.0
    return 1.0 + boost_max * min(best / max(ref, 0.1), 1.0)


def commodity_boost(
    weights: dict[str, float],
    candidate_commodity_ids: list[int],
    *,
    boost_max: float = BOOST_MAX,
    ref: float = BOOST_REF,
) -> float:
    """Commodity-keyed boost — candidate_commodity_ids are DB commodity ids."""
    return _hottest_boost(weights, [str(cid) for cid in candidate_commodity_ids], boost_max, ref)


def location_boost(
    weights: dict[str, float],
    candidate_place_names: list[str],
    *,
    boost_max: float = BOOST_MAX,
    ref: float = BOOST_REF,
) -> float:
    """
    City/state-keyed boost — call once per dimension (city_weights + [post_city],
    then separately state_weights + [post_state]). candidate_place_names are
    plain text (city or state name), normalized the same way as the write side
    (write_news_signals/write_post_signals): stripped + lowercased, no
    id-mapping table needed.
    """
    return _hottest_boost(weights, [s.strip().lower() for s in candidate_place_names], boost_max, ref)
