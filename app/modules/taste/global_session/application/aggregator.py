"""
Three-layer taste aggregator — application layer.

Responsibilities:
  1. SyncModuleToGlobal  — push unsynced commodity delta to global session
  2. MergeWeights        — blend persistent + global + module into final weights

Imports:
  - domain interfaces only (IModuleSessionRepository, IGlobalSessionRepository)
  - constants via session_taste public API (their __init__.py)
  - Never imports data/ from any sub-package
"""
from __future__ import annotations

from app.modules.taste.global_session.domain.entities import InfluenceWeights
from app.modules.taste.global_session.domain.interfaces import IGlobalSessionRepository
from app.modules.taste.session_taste import (
    AUTHOR_SESSION_CONF_THRESHOLD,
    CATEGORY_CONF_THRESHOLD,
    GLOBAL_SESSION_MAX_INFLUENCE,
    MODULE_SESSION_MAX_INFLUENCE,
    PERSISTENT_MIN_INFLUENCE,
    IModuleSessionRepository,
    global_commodity_threshold,
    module_commodity_threshold,
)


# ── Use case 1: Sync ──────────────────────────────────────────────────────────

class SyncModuleToGlobal:
    """
    Push unsynced commodity delta from one module session to global session.

    Called ONCE per feed request before MergeWeights reads global data.
    Only commodity syncs — CROSS_PLATFORM_DIMS rule enforced here.
    Write succeeds → mark_synced prevents double-counting on next call.
    Write fails  → mark_synced is NOT called → safe to retry next request.
    """

    def __init__(
        self,
        module_repo: IModuleSessionRepository,
        global_repo: IGlobalSessionRepository,
    ) -> None:
        self._m = module_repo
        self._g = global_repo

    def execute(self, profile_id: int, module: str) -> None:
        delta, snapshot = self._m.get_commodity_delta_and_snapshot(profile_id, module)
        if not delta:
            return
        self._g.write_commodity_delta(profile_id, delta)
        self._m.mark_synced(profile_id, module, snapshot)   # only after write


# ── Use case 2: Merge ─────────────────────────────────────────────────────────

class MergeWeights:
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

    Dimensions:
        category → 2-layer  (persistent + module)
        commodity → 3-layer (persistent + global + module)
        author   → 2-layer  (persistent + module, lower ceiling)
    """

    def __init__(
        self,
        module_repo: IModuleSessionRepository,
        global_repo: IGlobalSessionRepository,
    ) -> None:
        self._m = module_repo
        self._g = global_repo

    def execute(
        self,
        profile_id: int,
        module: str,
        dimension_type: str,
        persistent_weights: dict[str, float],
    ) -> dict[str, float]:
        # ── Gather module session scores ──────────────────────────────────────
        module_scores = self._m.read_dimension_scores(profile_id, module, dimension_type)

        # ── Gather global session scores (commodity only) ─────────────────────
        global_scores: dict[str, float] = {}
        if dimension_type == "commodity":
            global_scores = self._g.read_commodity_weights(profile_id)

        all_keys = set(persistent_weights) | set(module_scores) | set(global_scores)
        if not all_keys:
            return persistent_weights

        merged: dict[str, float] = {}
        for key in all_keys:
            pers_val = persistent_weights.get(key, 0.0)
            m_score  = module_scores.get(key, 0.0)
            g_score  = global_scores.get(key, 0.0)

            p_inf, g_inf, m_inf = self._influence(
                profile_id, module, dimension_type, key, pers_val
            )

            merged[key] = p_inf * pers_val + g_inf * g_score + m_inf * m_score

        return merged

    # ── Influence calculation ─────────────────────────────────────────────────

    def _influence(
        self,
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
            m_conf = self._m.read_dim_score(profile_id, module, dimension_type, key).conf
            m_inf = MODULE_SESSION_MAX_INFLUENCE * min(m_conf / max(threshold, 0.1), 1.0)
            g_inf = 0.0

        elif dimension_type == "commodity":
            m_threshold = module_commodity_threshold(pers_val)
            g_threshold = global_commodity_threshold(pers_val)
            m_score_obj = self._m.read_dim_score(profile_id, module, dimension_type, key)
            g_score_obj = self._g.read_commodity_score(profile_id, key)
            m_inf = MODULE_SESSION_MAX_INFLUENCE * min(
                m_score_obj.conf / max(m_threshold, 0.1), 1.0
            )
            g_inf = GLOBAL_SESSION_MAX_INFLUENCE * min(
                g_score_obj.conf / max(g_threshold, 0.1), 1.0
            )

        elif dimension_type == "author":
            # Lower ceiling for session-only author affinity (→ 1.1× not 1.2×)
            threshold = AUTHOR_SESSION_CONF_THRESHOLD
            m_conf = self._m.read_dim_score(profile_id, module, dimension_type, key).conf
            m_inf = (MODULE_SESSION_MAX_INFLUENCE * 0.35) * min(
                m_conf / max(threshold, 0.1), 1.0
            )
            g_inf = 0.0

        else:
            return 1.0, 0.0, 0.0

        p_inf = max(1.0 - g_inf - m_inf, PERSISTENT_MIN_INFLUENCE)
        return p_inf, g_inf, m_inf

    # ── Convenience: compute influence fractions only (for logging/debug) ─────

    def influence_for(
        self,
        profile_id: int,
        module: str,
        dimension_type: str,
        key: str,
        pers_val: float,
    ) -> InfluenceWeights:
        p, g, m = self._influence(profile_id, module, dimension_type, key, pers_val)
        return InfluenceWeights(persistent=p, global_session=g, module_session=m)
