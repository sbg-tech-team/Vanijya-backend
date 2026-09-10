"""
Trending recalculation job.

Velocity score = number of distinct profiles that interacted with an article
in the past TRENDING_LOOKBACK_H hours (open_article, dwell, like, share).

Pipeline:
  1. Count unique profiles per article over the lookback window.
  2. Filter out articles below TRENDING_MIN_UNIQUE_USERS.
  3. Upsert news_raw_trending (replace the full snapshot).
  4. Commit.

Wired into app.core.scheduler to run every 30–60 min.
Accesses data/models.py ORM directly per recommendation layer rules.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.modules.news.data.models import NewsInteractionEvent, NewsTrending
from app.modules.news.recommendation.constants import (
    TRENDING_LOOKBACK_H,
    TRENDING_MIN_UNIQUE_USERS,
)

log = logging.getLogger(__name__)

_TRENDING_INTERACTION_TYPES = frozenset({"open_article", "dwell", "like", "share_tap"})


def recalc_trending(db: Session) -> int:
    """
    Recompute and replace the full trending snapshot.
    Returns the number of articles now in trending.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - timedelta(hours=TRENDING_LOOKBACK_H)

    # Count distinct profiles per article in the lookback window
    rows = db.execute(
        select(
            NewsInteractionEvent.article_id,
            func.count(NewsInteractionEvent.profile_id.distinct()).label("unique_profiles"),
        )
        .where(
            NewsInteractionEvent.occurred_at >= cutoff,
            NewsInteractionEvent.event_type.in_(_TRENDING_INTERACTION_TYPES),
        )
        .group_by(NewsInteractionEvent.article_id)
        .having(
            func.count(NewsInteractionEvent.profile_id.distinct())
            >= TRENDING_MIN_UNIQUE_USERS
        )
    ).all()

    if not rows:
        log.info("recalc_trending: no articles met threshold, clearing trending table")
        db.execute(NewsTrending.__table__.delete())
        db.commit()
        return 0

    # Replace the entire snapshot atomically
    # Delete stale entries first, then bulk upsert
    db.execute(NewsTrending.__table__.delete())

    max_unique = max(r.unique_profiles for r in rows)

    db.execute(
        NewsTrending.__table__.insert(),
        [
            {
                "article_id": r.article_id,
                "velocity_score": r.unique_profiles / max(max_unique, 1),
                "unique_profiles": r.unique_profiles,
                "computed_at": now,
            }
            for r in rows
        ],
    )
    db.commit()

    log.info("recalc_trending: %d articles in trending snapshot", len(rows))
    return len(rows)
