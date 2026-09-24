"""
Global taste service — PostgreSQL-backed persistent cross-platform taste.

Manages the user_global_taste table. Runs the nightly promotion from
Redis global session into PostgreSQL when quality gates are passed.

Safety contract for promote_from_global_session:
    candidates = promote_from_global_session(db, rc, profile_id)
    db.commit()                          ← MUST commit before clearing Redis
    if candidates:
        from app.recommendation.global_session.service import clear
        clear(rc, profile_id)
"""
from __future__ import annotations

from datetime import datetime, timezone

import redis
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.recommendation.session_taste.constants import (
    PROMOTION_CONFIDENCE_GATE,
    PROMOTION_EVENT_GATE,
    PROMOTION_FACTOR,
    PROMOTION_QUALITY_GATE,
    TASTE_DECAY_LAMBDA,
    global_city_threshold,
    global_commodity_threshold,
    global_state_threshold,
)
from app.recommendation.global_session.service import read_all_dimension_data
from app.recommendation.global_taste.models import UserGlobalTaste
from app.recommendation.global_taste.schemas import GlobalTasteScore, PromotionCandidate
from app.shared.utils.time_decay import decayed_score

# trade_intent is recognized by the sync/storage layer but has no promotion
# formula yet — if it ever has data it's silently skipped below.
_PROMOTION_THRESHOLD_FNS = {
    "commodity": global_commodity_threshold,
    "city": global_city_threshold,
    "state": global_state_threshold,
}


# ── Read ──────────────────────────────────────────────────────────────────────

def get_weights(
    repo,
    profile_id: int,
    dimension_type: str,
) -> dict[str, float]:
    """Return decay-adjusted net weights for all keys of one dimension."""
    rows: list[UserGlobalTaste] = repo.global_taste_rows(profile_id, dimension_type)
    weights: dict[str, float] = {}
    for row in rows:
        net = decayed_score(row.positive_score, row.negative_score, row.last_event_at, TASTE_DECAY_LAMBDA)
        if net > 0:
            weights[row.dimension_key] = net
    return weights


def get_weights_bulk(
    repo,
    profile_id: int,
    dimension_types: tuple[str, ...],
) -> dict[str, dict[str, float]]:
    """get_weights for several dimensions in one query instead of one each."""
    rows: list[UserGlobalTaste] = repo.global_taste_rows_bulk(profile_id, dimension_types)
    result: dict[str, dict[str, float]] = {d: {} for d in dimension_types}
    for row in rows:
        net = decayed_score(row.positive_score, row.negative_score, row.last_event_at, TASTE_DECAY_LAMBDA)
        if net > 0:
            result[row.dimension_type][row.dimension_key] = net
    return result


def get_score(
    db: Session,
    profile_id: int,
    dimension_type: str,
    dimension_key: str,
) -> GlobalTasteScore | None:
    """Return the full score record for one key, or None if absent."""
    row: UserGlobalTaste | None = (
        db.query(UserGlobalTaste)
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


# ── Write ─────────────────────────────────────────────────────────────────────

def apply_promotion_delta(
    db: Session,
    profile_id: int,
    dimension_type: str,
    dimension_key: str,
    pos_delta: float,
) -> None:
    """
    Atomically add pos_delta to the existing positive_score.
    Creates the row if absent. Does not commit — caller is responsible.
    """
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
    db.execute(stmt)


def bulk_apply_promotion(
    db: Session,
    deltas: list[tuple[int, str, str, float]],
) -> None:
    """
    Bulk upsert for the nightly promotion job.
    Each tuple: (profile_id, dimension_type, dimension_key, pos_delta)
    Does not commit — caller is responsible.
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
        db.execute(stmt)


# ── Nightly promotion ─────────────────────────────────────────────────────────

def promote_from_global_session(
    db: Session,
    rc: redis.Redis,
    profile_id: int,
) -> list[PromotionCandidate]:
    """
    Nightly promotion: Global Session → Persistent Global Taste.

    For each cross-platform dimension (commodity, city, state — trade_intent
    has no promotion formula yet and is skipped) and each key within it that
    passes all three gates:
        Gate 1 — confidence_gate: conf >= 0.70 × threshold
        Gate 2 — quality_gate:    pos - neg*0.6 >= 20
        Gate 3 — event_gate:      cnt >= 10

    Promotion formula:
        global_delta = pos - neg*0.6
        persistent   += 0.15 × global_delta

    Returns the list of PromotionCandidates written.
    Caller MUST commit db BEFORE calling clear() on Redis.
    """
    all_data = read_all_dimension_data(rc, profile_id)
    if not all_data:
        return []

    candidates: list[PromotionCandidate] = []

    for dimension_type, raw_data in all_data.items():
        threshold_fn = _PROMOTION_THRESHOLD_FNS.get(dimension_type)
        if threshold_fn is None:
            continue

        for dkey, data in raw_data.items():
            pos  = data.get("pos", 0.0)
            neg  = data.get("neg", 0.0)
            conf = data.get("conf", 0.0)
            cnt  = int(data.get("cnt", 0))

            existing = get_score(db, profile_id, dimension_type, dkey)
            pers_score = existing.positive_score if existing else 0.0

            threshold = threshold_fn(pers_score)

            # Gate 1: confidence
            if conf < PROMOTION_CONFIDENCE_GATE * threshold:
                continue

            # Gate 2: quality (weighted taste)
            quality = pos - (neg * 0.6)
            if quality < PROMOTION_QUALITY_GATE:
                continue

            # Gate 3: events
            if cnt < PROMOTION_EVENT_GATE:
                continue

            global_delta = pos - (neg * 0.6)
            promotion_delta = PROMOTION_FACTOR * global_delta

            if promotion_delta <= 0:
                continue

            candidates.append(PromotionCandidate(
                profile_id=profile_id,
                dimension_type=dimension_type,
                dimension_key=dkey,
                delta=promotion_delta,
            ))

    if candidates:
        bulk_apply_promotion(db, [
            (c.profile_id, c.dimension_type, c.dimension_key, c.delta)
            for c in candidates
        ])

    return candidates
