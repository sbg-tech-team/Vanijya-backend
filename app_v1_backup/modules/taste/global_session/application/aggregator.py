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
    CROSS_PLATFORM_DIMS,
    GLOBAL_SESSION_MAX_INFLUENCE,
    MODULE_SESSION_MAX_INFLUENCE,
    PERSISTENT_MIN_INFLUENCE,
    IModuleSessionRepository,
    global_city_threshold,
    global_commodity_threshold,
    global_state_threshold,
    module_city_threshold,
    module_commodity_threshold,
    module_state_threshold,
)

# Dimensions with a real 3-layer MergeWeights._influence branch (global reads
# happen for these). trade_intent is in CROSS_PLATFORM_DIMS (so it syncs
# harmlessly, no-op while nothing writes to it) but has no blend behavior
# decided yet -- deliberately excluded here until that feature resumes.
_GLOBAL_BLENDED_DIMS = frozenset({"commodity", "city", "state"})


# ── Use case 1: Sync ──────────────────────────────────────────────────────────

class SyncModuleToGlobal:
    """
    Push unsynced deltas from one module session to global session, for every
    cross-platform dimension (CROSS_PLATFORM_DIMS) that has data.

    Called ONCE per feed request before MergeWeights reads global data --
    callers do not need to know which dimensions are cross-platform; this
    loops over all of them internally. Dimensions with no data (or no writer
    yet, e.g. trade_intent) are cheap no-ops.
    Write succeeds → mark_dimension_synced prevents double-counting on next call.
    Write fails  → not marked synced → safe to retry next request.
    """

    def __init__(
        self,
        module_repo: IModuleSessionRepository,
        global_repo: IGlobalSessionRepository,
    ) -> None:
        self._m = module_repo
        self._g = global_repo

    def execute(self, profile_id: int, module: str) -> None:
        for dimension_type in CROSS_PLATFORM_DIMS:
            delta, snapshot = self._m.get_dimension_delta_and_snapshot(
                profile_id, module, dimension_type
            )
            if not delta:
                continue
            self._g.write_dimension_delta(profile_id, dimension_type, delta)
            self._m.mark_dimension_synced(profile_id, module, dimension_type, snapshot)


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
        city     → 3-layer  (persistent + global + module)
        state    → 3-layer  (persistent + global + module)
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

        # ── Gather global session scores (blended dims only) ───────────────────
        global_scores: dict[str, float] = {}
        if dimension_type in _GLOBAL_BLENDED_DIMS:
            global_scores = self._g.read_dimension_weights(profile_id, dimension_type)

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
            g_score_obj = self._g.read_dimension_score(profile_id, dimension_type, key)
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

        elif dimension_type == "city":
            m_threshold = module_city_threshold(pers_val)
            g_threshold = global_city_threshold(pers_val)
            m_score_obj = self._m.read_dim_score(profile_id, module, dimension_type, key)
            g_score_obj = self._g.read_dimension_score(profile_id, dimension_type, key)
            m_inf = MODULE_SESSION_MAX_INFLUENCE * min(
                m_score_obj.conf / max(m_threshold, 0.1), 1.0
            )
            g_inf = GLOBAL_SESSION_MAX_INFLUENCE * min(
                g_score_obj.conf / max(g_threshold, 0.1), 1.0
            )

        elif dimension_type == "state":
            m_threshold = module_state_threshold(pers_val)
            g_threshold = global_state_threshold(pers_val)
            m_score_obj = self._m.read_dim_score(profile_id, module, dimension_type, key)
            g_score_obj = self._g.read_dimension_score(profile_id, dimension_type, key)
            m_inf = MODULE_SESSION_MAX_INFLUENCE * min(
                m_score_obj.conf / max(m_threshold, 0.1), 1.0
            )
            g_inf = GLOBAL_SESSION_MAX_INFLUENCE * min(
                g_score_obj.conf / max(g_threshold, 0.1), 1.0
            )

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
