"""
session_taste — public API and composition root.

This is the only file external callers (e.g. post application layer,
news application layer) should import from. Internal layers are private.

Usage:
    from app.modules.taste.session_taste import (
        write_signals,
        read_dimension_weights,
        get_commodity_delta_and_snapshot,
        mark_synced,
        SessionSignal,
        ActionType,
        IModuleSessionRepository,        # for type annotations
        RedisModuleSessionRepository,    # for manual wiring if needed
    )
"""
from __future__ import annotations

import redis as _redis

from app.modules.taste.session_taste.application.use_cases import (
    GetCommoditySyncDelta,
    MarkSynced,
    ReadDimScore,
    ReadDimensionWeights,
    WriteSignals,
)
from app.modules.taste.session_taste.data.redis_repository import (
    RedisModuleSessionRepository,
)
from app.modules.taste.session_taste.domain.constants import (  # re-exported
    AUTHOR_MIN_TASTE_DELTA,
    AUTHOR_SESSION_CONF_THRESHOLD,
    CATEGORY_CONF_THRESHOLD,
    CROSS_PLATFORM_DIMS,
    GLOBAL_SESSION_MAX_INFLUENCE,
    MODULE_SESSION_MAX_INFLUENCE,
    PERSISTENT_MIN_INFLUENCE,
    PROMOTION_CONFIDENCE_GATE,
    PROMOTION_EVENT_GATE,
    PROMOTION_FACTOR,
    PROMOTION_QUALITY_GATE,
    SIGNAL_WEIGHTS,
    TASTE_DECAY_LAMBDA,
    global_commodity_threshold,
    module_commodity_threshold,
)
from app.modules.taste.session_taste.domain.entities import (  # re-exported
    ActionType,
    DimScore,
    SessionSignal,
)
from app.modules.taste.session_taste.domain.exceptions import (  # re-exported
    SessionReadError,
    SessionTasteError,
    SessionWriteError,
)
from app.modules.taste.session_taste.domain.interfaces import (  # re-exported
    IModuleSessionRepository,
)


# ── Convenience functions (composition root wires repo + use case) ─────────────
# External callers pass an rc (redis.Redis) and call these directly.
# No need to instantiate repos or use-case objects manually.

def write_signals(
    rc: _redis.Redis,
    profile_id: int,
    module: str,
    signals: list[SessionSignal],
) -> None:
    """Write a batch of interaction signals into the module session hash."""
    WriteSignals(RedisModuleSessionRepository(rc)).execute(profile_id, module, signals)


def read_dimension_weights(
    rc: _redis.Redis,
    profile_id: int,
    module: str,
    dimension_type: str,
) -> dict[str, float]:
    """Return decay-adjusted net weights for one dimension. Empty if no session."""
    return ReadDimensionWeights(RedisModuleSessionRepository(rc)).execute(
        profile_id, module, dimension_type
    )


def read_dim_score(
    rc: _redis.Redis,
    profile_id: int,
    module: str,
    dimension_type: str,
    key: str,
) -> DimScore:
    """Return the full score record for one dimension key."""
    return ReadDimScore(RedisModuleSessionRepository(rc)).execute(
        profile_id, module, dimension_type, key
    )


def get_commodity_delta_and_snapshot(
    rc: _redis.Redis,
    profile_id: int,
    module: str,
) -> tuple[dict[str, float], dict[str, float]]:
    """Compute unsynced commodity delta. Returns (delta, snapshot)."""
    return GetCommoditySyncDelta(RedisModuleSessionRepository(rc)).execute(
        profile_id, module
    )


def mark_synced(
    rc: _redis.Redis,
    profile_id: int,
    module: str,
    snapshot: dict[str, float],
) -> None:
    """Record sync snapshot after a successful global session write."""
    MarkSynced(RedisModuleSessionRepository(rc)).execute(profile_id, module, snapshot)


__all__ = [
    # Convenience API
    "write_signals",
    "read_dimension_weights",
    "read_dim_score",
    "get_commodity_delta_and_snapshot",
    "mark_synced",
    # Domain entities (callers need these for constructing signals)
    "SessionSignal",
    "ActionType",
    "DimScore",
    # Domain interfaces (for type annotations)
    "IModuleSessionRepository",
    # Concrete implementation (for manual wiring)
    "RedisModuleSessionRepository",
    # Constants (re-exported so aggregator can import via this __init__)
    "SIGNAL_WEIGHTS",
    "TASTE_DECAY_LAMBDA",
    "CATEGORY_CONF_THRESHOLD",
    "AUTHOR_SESSION_CONF_THRESHOLD",
    "AUTHOR_MIN_TASTE_DELTA",
    "CROSS_PLATFORM_DIMS",
    "MODULE_SESSION_MAX_INFLUENCE",
    "GLOBAL_SESSION_MAX_INFLUENCE",
    "PERSISTENT_MIN_INFLUENCE",
    "PROMOTION_CONFIDENCE_GATE",
    "PROMOTION_QUALITY_GATE",
    "PROMOTION_EVENT_GATE",
    "PROMOTION_FACTOR",
    "module_commodity_threshold",
    "global_commodity_threshold",
    # Exceptions
    "SessionTasteError",
    "SessionWriteError",
    "SessionReadError",
]
