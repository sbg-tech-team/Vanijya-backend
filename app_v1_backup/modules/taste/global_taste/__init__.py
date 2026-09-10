"""
global_taste — public API and composition root.

Layer 3: persistent cross-platform taste (PostgreSQL user_global_taste table).

Usage:
    from app.modules.taste.global_taste import (
        read_global_taste_weights,
        promote_from_global_session,
        IGlobalTasteRepository,
        UserGlobalTaste,
    )
"""
from __future__ import annotations

import redis as _redis
from sqlalchemy.orm import Session as _Session

from app.modules.taste.global_session.data.redis_repository import (
    RedisGlobalSessionRepository,
)
from app.modules.taste.global_taste.application.use_cases import (
    PromoteFromGlobalSession,
    ReadGlobalTasteWeights,
)
from app.modules.taste.global_taste.data.models import UserGlobalTaste  # re-exported
from app.modules.taste.global_taste.data.repository import (
    PostgresGlobalTasteRepository,
)
from app.modules.taste.global_taste.domain.entities import (  # re-exported
    GlobalTasteScore,
    PromotionCandidate,
)
from app.modules.taste.global_taste.domain.exceptions import (  # re-exported
    GlobalTasteError,
    GlobalTasteReadError,
    GlobalTasteWriteError,
)
from app.modules.taste.global_taste.domain.interfaces import (  # re-exported
    IGlobalTasteRepository,
)


# ── Convenience functions ─────────────────────────────────────────────────────

def read_global_taste_weights(
    db: _Session,
    profile_id: int,
    dimension_type: str,
) -> dict[str, float]:
    """Return decay-adjusted weights from persistent global taste."""
    return ReadGlobalTasteWeights(
        PostgresGlobalTasteRepository(db)
    ).execute(profile_id, dimension_type)


def promote_from_global_session(
    db: _Session,
    rc: _redis.Redis,
    profile_id: int,
) -> list[PromotionCandidate]:
    """
    Run the nightly promotion for one profile.

    Safety contract:
        1. Writes qualifying deltas to PostgreSQL (inside this call)
        2. Caller MUST commit db BEFORE clearing Redis:
               candidates = promote_from_global_session(db, rc, profile_id)
               db.commit()
               if candidates:
                   from app.modules.taste.global_session import clear_global_session
                   clear_global_session(rc, profile_id)
    """
    return PromoteFromGlobalSession(
        global_session_repo=RedisGlobalSessionRepository(rc),
        global_taste_repo=PostgresGlobalTasteRepository(db),
    ).execute(profile_id)


__all__ = [
    "read_global_taste_weights",
    "promote_from_global_session",
    "UserGlobalTaste",
    "GlobalTasteScore",
    "PromotionCandidate",
    "IGlobalTasteRepository",
    "GlobalTasteError",
    "GlobalTasteWriteError",
    "GlobalTasteReadError",
]
