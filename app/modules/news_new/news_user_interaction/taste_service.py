# Taste Service — mirrors post_user_interaction/taste_service.py pattern
#
#   update_taste(db, user_id, dimension_type, dimension_key, positive_delta, negative_delta)
#     - PostgreSQL INSERT ... ON CONFLICT DO UPDATE (atomic upsert)
#     - does NOT commit — caller handles atomicity
#
#   get_taste_weights(db, user_id, dimension_type) → dict[str, float]
#     - applies exponential time decay (~30-day half-life)
#     - net score = decayed_positive - (negative * 0.6), floor at 0.05
#     - confidence blend with defaults until TASTE_BOOTSTRAP_EVENTS
