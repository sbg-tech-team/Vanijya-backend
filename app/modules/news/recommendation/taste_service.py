"""
Taste service — reads and writes UserNewsTaste rows.

Accessed by recommendation/engine.py (reads) and called via application
layer (writes go through INewsRepository.upsert_taste).
This service owns read logic only: decay, floor, confidence blend.
All writes happen through the repository to keep transaction control with the caller.

Accesses data/models.py directly (ORM) per recommendation layer rules.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.modules.news.data.models import UserNewsTaste
from app.modules.news.recommendation.constants import (
    DEFAULT_TASTE,
    TASTE_BOOTSTRAP_EVENTS,
    TASTE_DECAY_LAMBDA,
    TASTE_NEG_DISCOUNT,
    TASTE_SCORE_FLOOR,
)


class TasteService:

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_taste_weights(
        self,
        profile_id: int,
        dimension_type: str,
        role_id: int | None = None,
    ) -> dict[str, float]:
        """
        Return decayed taste weights for one dimension type.

        Applies 30-day exponential decay, floors at TASTE_SCORE_FLOOR, discounts
        negative scores by TASTE_NEG_DISCOUNT. For the category dimension,
        confidence-blends with DEFAULT_TASTE until TASTE_BOOTSTRAP_EVENTS.
        """
        rows = (
            self._db.query(UserNewsTaste)
            .filter(
                UserNewsTaste.profile_id == profile_id,
                UserNewsTaste.dimension_type == dimension_type,
            )
            .all()
        )

        if not rows:
            if dimension_type == "category" and role_id is not None:
                return dict(DEFAULT_TASTE.get(role_id, DEFAULT_TASTE[1]))
            return {}

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        scores: dict[str, float] = {}
        total_events = 0

        for row in rows:
            last_event = row.last_event_at
            if last_event.tzinfo is not None:
                last_event = last_event.replace(tzinfo=None)
            days_since = (now - last_event).total_seconds() / 86400.0
            decayed = row.positive_score * math.exp(-TASTE_DECAY_LAMBDA * days_since)
            net = decayed - (row.negative_score * TASTE_NEG_DISCOUNT)
            scores[row.dimension_key] = max(net, TASTE_SCORE_FLOOR)
            total_events += row.event_count

        if (
            dimension_type == "category"
            and role_id is not None
            and total_events < TASTE_BOOTSTRAP_EVENTS
        ):
            defaults = DEFAULT_TASTE.get(role_id, DEFAULT_TASTE[1])
            confidence = total_events / TASTE_BOOTSTRAP_EVENTS
            for key, default_val in defaults.items():
                learned = scores.get(key, TASTE_SCORE_FLOOR)
                scores[key] = confidence * learned + (1 - confidence) * float(default_val)

        return scores

    def seed_taste_from_role(self, profile_id: int, role_id: int) -> None:
        """
        Insert initial category rows from role defaults.
        ON CONFLICT DO NOTHING — never overwrites existing learned data.
        Intended for onboarding; not called automatically on interactions.
        Commits.
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        defaults = DEFAULT_TASTE.get(role_id, DEFAULT_TASTE[1])

        for factor, default_score in defaults.items():
            stmt = (
                pg_insert(UserNewsTaste)
                .values(
                    profile_id=profile_id,
                    dimension_type="category",
                    dimension_key=factor,
                    positive_score=float(default_score),
                    negative_score=0.0,
                    event_count=0,
                    last_event_at=now,
                )
                .on_conflict_do_nothing()
            )
            self._db.execute(stmt)

        self._db.commit()
