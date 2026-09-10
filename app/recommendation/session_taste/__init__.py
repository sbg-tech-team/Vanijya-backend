"""
session_taste — public API.

Usage:
    from app.recommendation.session_taste import (
        write_signals,
        read_dimension_weights,
        get_dimension_delta_and_snapshot,
        mark_dimension_synced,
        SessionSignal,
        ActionType,
    )
"""
from app.recommendation.session_taste.service import (
    write_signals,
    read_dimension_weights,
    read_dimension_scores,
    read_dim_score,
    get_dimension_delta_and_snapshot,
    mark_dimension_synced,
    session_exists,
)
from app.recommendation.session_taste.schemas import (
    ActionType,
    DimScore,
    SessionSignal,
)
from app.recommendation.session_taste.constants import (
    AUTHOR_MIN_TASTE_DELTA,
    AUTHOR_SESSION_CONF_THRESHOLD,
    CATEGORY_CONF_THRESHOLD,
    CROSS_PLATFORM_DIMS,
    GLOBAL_SESSION_MAX_INFLUENCE,
    GLOBAL_SESSION_TTL,
    MODULE_SESSION_MAX_INFLUENCE,
    MODULE_SESSION_TTL,
    PERSISTENT_MIN_INFLUENCE,
    PROMOTION_CONFIDENCE_GATE,
    PROMOTION_EVENT_GATE,
    PROMOTION_FACTOR,
    PROMOTION_QUALITY_GATE,
    SIGNAL_WEIGHTS,
    TASTE_DECAY_LAMBDA,
    global_city_threshold,
    global_commodity_threshold,
    global_state_threshold,
    module_city_threshold,
    module_commodity_threshold,
    module_state_threshold,
)

__all__ = [
    # Service functions
    "write_signals",
    "read_dimension_weights",
    "read_dimension_scores",
    "read_dim_score",
    "get_dimension_delta_and_snapshot",
    "mark_dimension_synced",
    "session_exists",
    # Schemas
    "ActionType",
    "DimScore",
    "SessionSignal",
    # Constants
    "SIGNAL_WEIGHTS",
    "TASTE_DECAY_LAMBDA",
    "MODULE_SESSION_TTL",
    "GLOBAL_SESSION_TTL",
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
    "module_city_threshold",
    "global_city_threshold",
    "module_state_threshold",
    "global_state_threshold",
]
