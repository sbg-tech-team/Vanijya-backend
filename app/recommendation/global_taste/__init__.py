"""
global_taste — public API.

Usage:
    from app.recommendation.global_taste import (
        read_global_taste_weights,
        promote_from_global_session,
        UserGlobalTaste,
        PromotionCandidate,
    )
"""
from app.recommendation.global_taste.service import (
    get_weights as read_global_taste_weights,
    get_score,
    apply_promotion_delta,
    bulk_apply_promotion,
    promote_from_global_session,
)
from app.recommendation.global_taste.models import UserGlobalTaste
from app.recommendation.global_taste.schemas import (
    GlobalTasteScore,
    PromotionCandidate,
)

__all__ = [
    # Service
    "read_global_taste_weights",
    "get_score",
    "apply_promotion_delta",
    "bulk_apply_promotion",
    "promote_from_global_session",
    # Model
    "UserGlobalTaste",
    # Schemas
    "GlobalTasteScore",
    "PromotionCandidate",
]
