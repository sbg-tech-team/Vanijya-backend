"""
Three-layer taste aggregator.

Responsibilities:
  1. sync_module_to_global  — push unsynced commodity delta to global session
  2. merge_weights          — blend persistent + global + module into final weights

Imports service modules directly (not via __init__.py) to avoid circular imports.
"""
from __future__ import annotations

import redis

from app.recommendation.session_taste.constants import (
    AUTHOR_SESSION_CONF_THRESHOLD,
    CATEGORY_CONF_THRESHOLD,
    CROSS_PLATFORM_DIMS,
    GLOBAL_SESSION_MAX_INFLUENCE,
    MODULE_SESSION_MAX_INFLUENCE,
    PERSISTENT_MIN_INFLUENCE,
    global_city_threshold,
    global_commodity_threshold,
    global_state_threshold,
    module_city_threshold,
    module_commodity_threshold,
    module_state_threshold,
)
from app.recommendation.session_taste import service as session_svc
from app.recommendation.global_session import service as global_svc
from app.recommendation.global_session.schemas import InfluenceWeights

# Dimensions with a real 3-layer MergeWeights._influence branch (global scores
# actually get read/blended). trade_intent is in CROSS_PLATFORM_DIMS (so it
# syncs as a no-op) but has no blend behavior decided yet, so it's deliberately
# excluded here.
_GLOBAL_BLENDED_DIMS = frozenset({"commodity", "city", "state"})


# ── Sync ──────────────────────────────────────────────────────────────────────

def sync_module_to_global(
    rc: redis.Redis,
    profile_id: int,
    module: str,
) -> None:
    """
    Push unsynced delta from one module session to global session, for every
    cross-platform dimension.

    Called ONCE per feed request before merge_weights reads global data.
    Only CROSS_PLATFORM_DIMS sync — enforced here.
    Per dimension: write succeeds → mark synced (prevents double-counting on
    next call). Write fails → mark NOT called → safe to retry next request.
    """
    for dimension_type in CROSS_PLATFORM_DIMS:
        delta, snapshot = session_svc.get_dimension_delta_and_snapshot(rc, profile_id, module, dimension_type)
        if not delta:
            continue
        global_svc.write_dimension_delta(rc, profile_id, dimension_type, delta)
        session_svc.mark_dimension_synced(rc, profile_id, module, dimension_type, snapshot)   # only after write


# ── Merge ─────────────────────────────────────────────────────────────────────

def merge_weights(
    rc: redis.Redis,
    profile_id: int,
    module: str,
    dimension_type: str,
    persistent_weights: dict[str, float],
) -> dict[str, float]:
    """
    Blend persistent + global session + module session into final feed weights.

    Formula (per key):
        g_inf = GLOBAL_MAX  × min(g_conf / g_threshold, 1.0)
        m_inf = MODULE_MAX  × min(m_conf / m_threshold, 1.0)
        p_inf = max(1.0 - g_inf - m_inf, PERSISTENT_MIN)
        merged[key] = p_inf × persistent + g_inf × global + m_inf × module

    Persistent never drops below 54%.
    Global never exceeds 15%.
    Module never exceeds 31%.

    Must be called AFTER sync_module_to_global for cross-platform dimensions
    (commodity, city, state).
    """
    module_scores = session_svc.read_dimension_scores(rc, profile_id, module, dimension_type)

    global_scores: dict[str, float] = {}
    if dimension_type in _GLOBAL_BLENDED_DIMS:
        global_scores = global_svc.read_dimension_weights(rc, profile_id, dimension_type)

    all_keys = set(persistent_weights) | set(module_scores) | set(global_scores)
    if not all_keys:
        return persistent_weights

    merged: dict[str, float] = {}
    for key in all_keys:
        pers_val = persistent_weights.get(key, 0.0)
        m_score  = module_scores.get(key, 0.0)
        g_score  = global_scores.get(key, 0.0)

        p_inf, g_inf, m_inf = _influence(rc, profile_id, module, dimension_type, key, pers_val)

        merged[key] = p_inf * pers_val + g_inf * g_score + m_inf * m_score

    return merged


def influence_for(
    rc: redis.Redis,
    profile_id: int,
    module: str,
    dimension_type: str,
    key: str,
    pers_val: float,
) -> InfluenceWeights:
    """Return influence fractions for one dimension key (for logging/debug)."""
    p, g, m = _influence(rc, profile_id, module, dimension_type, key, pers_val)
    return InfluenceWeights(persistent=p, global_session=g, module_session=m)


# ── Influence calculation (internal) ──────────────────────────────────────────

def _influence(
    rc: redis.Redis,
    profile_id: int,
    module: str,
    dimension_type: str,
    key: str,
    pers_val: float,
) -> tuple[float, float, float]:
    """
    Returns (p_influence, g_influence, m_influence) for one dimension key.
    All three sum to 1.0; persistent is always >= PERSISTENT_MIN (0.54).
    """
    if dimension_type == "category":
        threshold = CATEGORY_CONF_THRESHOLD
        m_conf = session_svc.read_dim_score(rc, profile_id, module, dimension_type, key).conf
        m_inf = MODULE_SESSION_MAX_INFLUENCE * min(m_conf / max(threshold, 0.1), 1.0)
        g_inf = 0.0

    elif dimension_type == "commodity":
        m_threshold = module_commodity_threshold(pers_val)
        g_threshold = global_commodity_threshold(pers_val)
        m_score_obj = session_svc.read_dim_score(rc, profile_id, module, dimension_type, key)
        g_score_obj = global_svc.read_dimension_score(rc, profile_id, dimension_type, key)
        m_inf = MODULE_SESSION_MAX_INFLUENCE * min(
            m_score_obj.conf / max(m_threshold, 0.1), 1.0
        )
        g_inf = GLOBAL_SESSION_MAX_INFLUENCE * min(
            g_score_obj.conf / max(g_threshold, 0.1), 1.0
        )

    elif dimension_type == "city":
        m_threshold = module_city_threshold(pers_val)
        g_threshold = global_city_threshold(pers_val)
        m_score_obj = session_svc.read_dim_score(rc, profile_id, module, dimension_type, key)
        g_score_obj = global_svc.read_dimension_score(rc, profile_id, dimension_type, key)
        m_inf = MODULE_SESSION_MAX_INFLUENCE * min(
            m_score_obj.conf / max(m_threshold, 0.1), 1.0
        )
        g_inf = GLOBAL_SESSION_MAX_INFLUENCE * min(
            g_score_obj.conf / max(g_threshold, 0.1), 1.0
        )

    elif dimension_type == "state":
        m_threshold = module_state_threshold(pers_val)
        g_threshold = global_state_threshold(pers_val)
        m_score_obj = session_svc.read_dim_score(rc, profile_id, module, dimension_type, key)
        g_score_obj = global_svc.read_dimension_score(rc, profile_id, dimension_type, key)
        m_inf = MODULE_SESSION_MAX_INFLUENCE * min(
            m_score_obj.conf / max(m_threshold, 0.1), 1.0
        )
        g_inf = GLOBAL_SESSION_MAX_INFLUENCE * min(
            g_score_obj.conf / max(g_threshold, 0.1), 1.0
        )

    elif dimension_type == "author":
        # Lower ceiling for session-only author affinity (→ 1.1× not 1.2×)
        threshold = AUTHOR_SESSION_CONF_THRESHOLD
        m_conf = session_svc.read_dim_score(rc, profile_id, module, dimension_type, key).conf
        m_inf = (MODULE_SESSION_MAX_INFLUENCE * 0.35) * min(
            m_conf / max(threshold, 0.1), 1.0
        )
        g_inf = 0.0

    else:
        return 1.0, 0.0, 0.0

    p_inf = max(1.0 - g_inf - m_inf, PERSISTENT_MIN_INFLUENCE)
    return p_inf, g_inf, m_inf
