"""
Shared recommendation infrastructure.

Sub-modules:
    session_taste   — per-module Redis session taste (write_signals, read_dimension_weights)
    global_session  — cross-module Redis aggregation (sync_module_to_global, merge_weights)
    global_taste    — persistent PostgreSQL taste (promote_from_global_session)
"""

from app.recommendation.amplify import (  # noqa: F401,E402
    BOOST_MAX,
    BOOST_REF,
    commodity_boost,
    commodity_id_by_name,
    commodity_ids_for,
    get_amplify_weights,
    location_boost,
    write_commodity_signals,
    write_news_signals,
    write_post_signals,
)
