"""
global_session — public API and composition root.

Usage:
    from app.modules.taste.global_session import (
        sync_module_to_global,
        merge_weights,
        read_global_weights,
        IGlobalSessionRepository,
        RedisGlobalSessionRepository,
        InfluenceWeights,
    )
"""
from __future__ import annotations

import redis as _redis

from app.modules.taste.session_taste import (
    IModuleSessionRepository,
    RedisModuleSessionRepository,
)
from app.modules.taste.global_session.application.aggregator import (
    MergeWeights,
    SyncModuleToGlobal,
)
from app.modules.taste.global_session.application.use_cases import (
    ClearGlobalSession,
    ReadAllCommodityData,
    ReadGlobalWeights,
    WriteGlobalDelta,
)
from app.modules.taste.global_session.data.redis_repository import (
    RedisGlobalSessionRepository,
)
from app.modules.taste.global_session.domain.entities import (  # re-exported
    GlobalDimScore,
    InfluenceWeights,
)
from app.modules.taste.global_session.domain.exceptions import (  # re-exported
    GlobalSessionError,
    GlobalSessionReadError,
    GlobalSessionWriteError,
)
from app.modules.taste.global_session.domain.interfaces import (  # re-exported
    IGlobalSessionRepository,
)


# ── Convenience functions ─────────────────────────────────────────────────────

def sync_module_to_global(
    rc: _redis.Redis,
    profile_id: int,
    module: str,
) -> None:
    """
    Push the unsynced commodity delta from one module session to global.
    Call once per feed request, before merge_weights.
    """
    m_repo = RedisModuleSessionRepository(rc)
    g_repo = RedisGlobalSessionRepository(rc)
    SyncModuleToGlobal(m_repo, g_repo).execute(profile_id, module)


def merge_weights(
    rc: _redis.Redis,
    profile_id: int,
    module: str,
    dimension_type: str,
    persistent_weights: dict[str, float],
) -> dict[str, float]:
    """
    Blend persistent + global session + module session into final feed weights.

    Must be called AFTER sync_module_to_global for commodity dimension.
    For category and author (2-layer), sync has no effect but is still harmless.
    """
    m_repo = RedisModuleSessionRepository(rc)
    g_repo = RedisGlobalSessionRepository(rc)
    return MergeWeights(m_repo, g_repo).execute(
        profile_id, module, dimension_type, persistent_weights
    )


def read_global_weights(
    rc: _redis.Redis,
    profile_id: int,
) -> dict[str, float]:
    """Return decayed commodity weights from global session (no module merge)."""
    return ReadGlobalWeights(RedisGlobalSessionRepository(rc)).execute(profile_id)


def read_all_commodity_data(
    rc: _redis.Redis,
    profile_id: int,
) -> dict[str, dict[str, float]]:
    """Raw commodity data for the nightly promotion job."""
    return ReadAllCommodityData(RedisGlobalSessionRepository(rc)).execute(profile_id)


def clear_global_session(rc: _redis.Redis, profile_id: int) -> None:
    """Delete global session after nightly promotion commits to DB."""
    ClearGlobalSession(RedisGlobalSessionRepository(rc)).execute(profile_id)


__all__ = [
    "sync_module_to_global",
    "merge_weights",
    "read_global_weights",
    "read_all_commodity_data",
    "clear_global_session",
    "InfluenceWeights",
    "GlobalDimScore",
    "IGlobalSessionRepository",
    "RedisGlobalSessionRepository",
    "GlobalSessionError",
    "GlobalSessionWriteError",
    "GlobalSessionReadError",
]
