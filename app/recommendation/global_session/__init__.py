"""
global_session — public API.

Usage:
    from app.recommendation.global_session import (
        sync_module_to_global,
        merge_weights,
        read_global_weights,
        read_all_dimension_data,
        clear_global_session,
        InfluenceWeights,
    )
"""
from app.recommendation.global_session.aggregator import (
    sync_module_to_global,
    merge_weights,
    influence_for,
)
from app.recommendation.global_session.service import (
    write_dimension_delta,
    read_dimension_weights as read_global_weights,
    read_dimension_score,
    read_all_dimension_data,
    clear as clear_global_session,
    session_exists as global_session_exists,
    list_active_profile_ids,
)
from app.recommendation.global_session.schemas import (
    GlobalDimScore,
    InfluenceWeights,
)

__all__ = [
    # Aggregator
    "sync_module_to_global",
    "merge_weights",
    "influence_for",
    # Service
    "write_dimension_delta",
    "read_global_weights",
    "read_dimension_score",
    "read_all_dimension_data",
    "clear_global_session",
    "global_session_exists",
    "list_active_profile_ids",
    # Schemas
    "GlobalDimScore",
    "InfluenceWeights",
]
