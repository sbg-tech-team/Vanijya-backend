import math
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.modules.news_new.news_user_interaction.constants import (
    DEFAULT_TASTE,
    TASTE_BOOTSTRAP_EVENTS,
    TASTE_DECAY_LAMBDA,
)
from app.modules.news_new.news_user_interaction.models import UserNewsTaste

_SCORE_FLOOR = 0.05
_NEG_DISCOUNT = 0.6


def update_taste(
    db: Session,
    profile_id: int,
    dimension_type: str,
    dimension_key: str,
    positive_delta: float,
    negative_delta: float = 0.0,
    event_count: int = 1,
) -> None:
    """
    Atomic upsert of one taste row.
    Does NOT commit — caller owns the transaction so taste and the triggering
    interaction (like / open) commit together.
    """
    now = datetime.now(timezone.utc)
    stmt = (
        pg_insert(UserNewsTaste.__table__)
        .values(
            profile_id=profile_id,
            dimension_type=dimension_type,
            dimension_key=dimension_key,
            positive_score=positive_delta,
            negative_score=negative_delta,
            event_count=event_count,
            last_event_at=now,
        )
        .on_conflict_do_update(
            index_elements=["profile_id", "dimension_type", "dimension_key"],
            set_={
                "positive_score": UserNewsTaste.__table__.c.positive_score + positive_delta,
                "negative_score": UserNewsTaste.__table__.c.negative_score + negative_delta,
                "event_count": UserNewsTaste.__table__.c.event_count + event_count,
                "last_event_at": now,
            },
        )
    )
    db.execute(stmt)


def get_taste_weights(
    db: Session,
    profile_id: int,
    dimension_type: str,
    role_id: int | None = None,
) -> dict[str, float]:
    """
    Returns taste weights for one dimension type.
    Applies 30-day exponential decay, floors at _SCORE_FLOOR, and confidence-
    blends with role defaults for the category dimension until bootstrapped.
    """
    rows = (
        db.query(UserNewsTaste)
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

    now = datetime.now(timezone.utc)
    scores: dict[str, float] = {}
    total_events = 0

    for row in rows:
        days_since = (now - row.last_event_at).total_seconds() / 86400
        decayed = row.positive_score * math.exp(-TASTE_DECAY_LAMBDA * days_since)
        net = decayed - (row.negative_score * _NEG_DISCOUNT)
        scores[row.dimension_key] = max(net, _SCORE_FLOOR)
        total_events += row.event_count

    if dimension_type == "category" and role_id is not None and total_events < TASTE_BOOTSTRAP_EVENTS:
        defaults = DEFAULT_TASTE.get(role_id, DEFAULT_TASTE[1])
        confidence = total_events / TASTE_BOOTSTRAP_EVENTS
        for key, default_val in defaults.items():
            learned = scores.get(key, _SCORE_FLOOR)
            scores[key] = confidence * learned + (1 - confidence) * float(default_val)

    return scores


def seed_taste_from_role(db: Session, profile_id: int, role_id: int) -> None:
    """
    Insert initial category rows from role defaults.
    ON CONFLICT DO NOTHING — never overwrites existing learned data.
    Intended for onboarding; not called automatically on interactions.
    """
    now = datetime.now(timezone.utc)
    defaults = DEFAULT_TASTE.get(role_id, DEFAULT_TASTE[1])

    for factor, default_score in defaults.items():
        stmt = (
            pg_insert(UserNewsTaste.__table__)
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
        db.execute(stmt)

    db.commit()
