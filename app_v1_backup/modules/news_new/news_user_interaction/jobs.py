"""
Scheduled jobs for the news_user_interaction slice.

recalc_trending()  — recompute velocity scores from recent interactions.
                     Wired into scheduler every 5 min.

Velocity formula (mirrors the old news module):
    velocity = weighted_signal_sum / log1p(unique_profile_count)

Signals come from NewsInteractionEvent (impression, dwell, open_article,
share_tap, revisit) plus NewsLike, NewsSave, NewsShare. SIGNAL_WEIGHTS from
constants.py drives the per-event weights so the trending job stays consistent
with the taste-update write path.
"""
import logging
from datetime import datetime, timedelta, timezone
from math import log1p

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database.session import SessionLocal
from app.modules.news_new.news_user_interaction.constants import (
    SIGNAL_WEIGHTS,
    TRENDING_LOOKBACK_H,
    TRENDING_MIN_UNIQUE_USERS,
)
from app.modules.news_new.news_user_interaction.models import (
    NewsInteractionEvent,
    NewsLike,
    NewsSave,
    NewsShare,
    NewsTrending,
)
from app.modules.news_new.news_user_interaction.service import classify_dwell

log = logging.getLogger(__name__)


def _accumulate(
    agg: dict,
    article_id,
    profile_id: int,
    signal_key: str,
) -> None:
    """Add one signal to the running aggregation dict."""
    if article_id not in agg:
        agg[article_id] = {"profiles": set(), "score": 0.0}
    agg[article_id]["profiles"].add(profile_id)
    pos, _ = SIGNAL_WEIGHTS.get(signal_key, (0.0, 0.0))
    agg[article_id]["score"] += pos


def recalc_trending(db: Session | None = None) -> int:
    """
    Recompute velocity scores from the last TRENDING_LOOKBACK_H hours of
    interactions. Upserts NewsTrending rows and removes articles that no
    longer meet the minimum unique-profile threshold.
    Returns the number of trending rows written.
    """
    own_db = db is None
    if own_db:
        db = SessionLocal()

    try:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=TRENDING_LOOKBACK_H)
        agg: dict = {}

        # ── Interaction events ────────────────────────────────────────────────
        events = db.execute(
            select(NewsInteractionEvent).where(NewsInteractionEvent.created_at >= cutoff)
        ).scalars().all()

        for ev in events:
            if ev.event_type == "dwell" and ev.value_ms is not None:
                key = classify_dwell(ev.value_ms)
            else:
                key = ev.event_type
            _accumulate(agg, ev.article_id, ev.profile_id, key)

        # ── Likes ─────────────────────────────────────────────────────────────
        for like in db.execute(
            select(NewsLike).where(NewsLike.created_at >= cutoff)
        ).scalars():
            _accumulate(agg, like.article_id, like.profile_id, "like")

        # ── Saves ─────────────────────────────────────────────────────────────
        for save in db.execute(
            select(NewsSave).where(NewsSave.created_at >= cutoff)
        ).scalars():
            _accumulate(agg, save.article_id, save.profile_id, "save")

        # ── Shares ────────────────────────────────────────────────────────────
        for share in db.execute(
            select(NewsShare).where(NewsShare.created_at >= cutoff)
        ).scalars():
            _accumulate(agg, share.article_id, share.profile_id, "share")

        # ── Compute velocity and rank ─────────────────────────────────────────
        ranked = []
        for article_id, data in agg.items():
            unique = len(data["profiles"])
            if unique < TRENDING_MIN_UNIQUE_USERS:
                continue
            velocity = data["score"] / max(log1p(unique), 1.0)
            ranked.append((article_id, velocity))

        ranked.sort(key=lambda x: x[1], reverse=True)

        # ── Upsert trending rows ──────────────────────────────────────────────
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        active_ids = set()

        for rank, (article_id, velocity) in enumerate(ranked, start=1):
            active_ids.add(article_id)
            existing = db.execute(
                select(NewsTrending).where(NewsTrending.article_id == article_id)
            ).scalar_one_or_none()

            if existing:
                existing.velocity_score = velocity
                existing.trending_rank = rank
                existing.computed_at = now
                db.add(existing)
            else:
                db.add(NewsTrending(
                    article_id=article_id,
                    velocity_score=velocity,
                    trending_rank=rank,
                    computed_at=now,
                ))

        # ── Remove articles that dropped out of trending ───────────────────────
        stale = db.execute(
            select(NewsTrending).where(NewsTrending.article_id.notin_(active_ids))
        ).scalars().all()
        for row in stale:
            db.delete(row)

        db.commit()
        log.info("news_new.recalc_trending: upserted=%d removed=%d", len(ranked), len(stale))
        return len(ranked)

    except Exception:
        db.rollback()
        log.exception("news_new.recalc_trending failed")
        raise
    finally:
        if own_db:
            db.close()
