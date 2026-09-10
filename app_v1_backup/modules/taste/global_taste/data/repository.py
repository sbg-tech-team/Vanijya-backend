"""
PostgreSQL implementation of IGlobalTasteRepository.

Data layer — imports from domain/ and core/ only.
Uses pg_insert (ON CONFLICT DO UPDATE) for atomic upserts, consistent with
the pattern in post_user_interaction/taste_service.py.
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.modules.taste.session_taste.domain.constants import TASTE_DECAY_LAMBDA
from app.modules.taste.global_taste.domain.entities import GlobalTasteScore
from app.modules.taste.global_taste.domain.interfaces import IGlobalTasteRepository
from app.modules.taste.global_taste.data.models import UserGlobalTaste


class PostgresGlobalTasteRepository(IGlobalTasteRepository):

    def __init__(self, db: Session) -> None:
        self._db = db

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_weights(
        self,
        profile_id: int,
        dimension_type: str,
    ) -> dict[str, float]:
        rows: list[UserGlobalTaste] = (
            self._db.query(UserGlobalTaste)
            .filter(
                UserGlobalTaste.profile_id == profile_id,
                UserGlobalTaste.dimension_type == dimension_type,
            )
            .all()
        )
        now = time.time()
        weights: dict[str, float] = {}
        for row in rows:
            ts = (
                row.last_event_at.timestamp()
                if row.last_event_at
                else 0.0
            )
            days = (now - ts) / 86400.0 if ts else 0.0
            decayed = row.positive_score * math.exp(-TASTE_DECAY_LAMBDA * days)
            net = decayed - (row.negative_score * 0.6)
            if net > 0:
                weights[row.dimension_key] = net
        return weights

    def get_score(
        self,
        profile_id: int,
        dimension_type: str,
        dimension_key: str,
    ) -> GlobalTasteScore | None:
        row: UserGlobalTaste | None = (
            self._db.query(UserGlobalTaste)
            .filter(
                UserGlobalTaste.profile_id == profile_id,
                UserGlobalTaste.dimension_type == dimension_type,
                UserGlobalTaste.dimension_key == dimension_key,
            )
            .first()
        )
        if row is None:
            return None
        return GlobalTasteScore(
            profile_id=row.profile_id,
            dimension_type=row.dimension_type,
            dimension_key=row.dimension_key,
            positive_score=row.positive_score,
            negative_score=row.negative_score,
            event_count=row.event_count,
            last_event_at_unix=int(row.last_event_at.timestamp()) if row.last_event_at else 0,
        )

    # ── Write ─────────────────────────────────────────────────────────────────

    def apply_promotion_delta(
        self,
        profile_id: int,
        dimension_type: str,
        dimension_key: str,
        pos_delta: float,
    ) -> None:
        now = datetime.now(timezone.utc)
        stmt = (
            pg_insert(UserGlobalTaste)
            .values(
                profile_id=profile_id,
                dimension_type=dimension_type,
                dimension_key=dimension_key,
                positive_score=pos_delta,
                negative_score=0.0,
                event_count=1,
                last_event_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                constraint="uq_user_global_taste_profile_dim",
                set_={
                    "positive_score": UserGlobalTaste.positive_score + pos_delta,
                    "event_count":    UserGlobalTaste.event_count + 1,
                    "last_event_at":  now,
                    "updated_at":     now,
                },
            )
        )
        self._db.execute(stmt)

    def bulk_apply_promotion(
        self,
        deltas: list[tuple[int, str, str, float]],
    ) -> None:
        """
        Bulk upsert for the nightly promotion job.
        Each tuple: (profile_id, dimension_type, dimension_key, pos_delta)
        """
        if not deltas:
            return
        now = datetime.now(timezone.utc)
        for profile_id, dimension_type, dimension_key, pos_delta in deltas:
            stmt = (
                pg_insert(UserGlobalTaste)
                .values(
                    profile_id=profile_id,
                    dimension_type=dimension_type,
                    dimension_key=dimension_key,
                    positive_score=pos_delta,
                    negative_score=0.0,
                    event_count=1,
                    last_event_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    constraint="uq_user_global_taste_profile_dim",
                    set_={
                        "positive_score": UserGlobalTaste.positive_score + pos_delta,
                        "event_count":    UserGlobalTaste.event_count + 1,
                        "last_event_at":  now,
                        "updated_at":     now,
                    },
                )
            )
            self._db.execute(stmt)
