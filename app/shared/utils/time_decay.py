"""
Shared time-decay math — the same exponential-decay taste formula and
freshness-boost formula were independently reimplemented in
recommendation/global_session/service.py, recommendation/session_taste/service.py,
recommendation/global_taste/service.py, and modules/post/recommendation/
session_taste/taste_service.py (decay), plus modules/post/recommendation/
constants.py + engine.py + application/use_cases/get_post.py (freshness).
Consolidated here so every caller shares one implementation.
"""
from __future__ import annotations

import math
import time
from datetime import datetime


def decayed_score(
    positive: float,
    negative: float,
    last_event_at: datetime | float | None,
    lam: float,
    neg_discount: float = 0.6,
) -> float:
    """
    Net taste score after exponential time decay.

    decayed = positive * exp(-lam * days_since_last_event)
    net     = decayed - negative * neg_discount

    `last_event_at` may be a datetime (naive treated as already-elapsed since
    epoch is meaningless for it, so callers should pass timezone-aware
    datetimes) or a unix timestamp (int/float); None means "no event yet",
    which returns a decay of exactly `positive` (days=0).
    """
    if last_event_at is None:
        ts = 0.0
    elif isinstance(last_event_at, datetime):
        ts = last_event_at.timestamp()
    else:
        ts = float(last_event_at)

    now = time.time()
    days = (now - ts) / 86400.0 if ts else 0.0
    decayed = positive * math.exp(-lam * days)
    return decayed - (negative * neg_discount)


def freshness_boost(created_at: datetime, peak: float, tau_hours: float) -> float:
    """
    Continuous freshness multiplier: 1.0 + peak * exp(-age_hours / tau_hours).

    Peak at age=0 is (1.0 + peak); fades back toward 1.0 as tau_hours pass.
    """
    from datetime import timezone

    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    age_h = max(0.0, (datetime.now(timezone.utc) - created_at).total_seconds() / 3600)
    return 1.0 + peak * math.exp(-age_h / tau_hours)
