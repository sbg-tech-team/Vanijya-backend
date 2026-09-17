"""
Post User Interaction Service

Write paths:
  process_interaction_batch()  – batch endpoint handler (impression, dwell, open_*, link_click)
  record_revisit_event()       – called from post/service._record_view() on duplicate view
  record_interaction()         – synchronous taste update on like / save / comment / share


Signal helpers (used by jobs.py):
  classify_dwell()             – bucket a dwell_ms value into a signal key
  derive_signal()              – (positive_delta, negative_delta) from an event
"""
import logging
from datetime import datetime, timezone, timedelta

import redis
from sqlalchemy import text

from app.modules.post.recommendation.session_taste.constants import (
    AUTHOR_TASTE_MIN_DELTA,
    CATEGORY_NAMES,
    DEFAULT_TASTE,
    DWELL_BOUNCE_MS,
    DWELL_LONG_MS,
    DWELL_SEEN_MS,
    DWELL_SHORT_MS,
    DWELL_VALUE_CAP_MS,
    MAX_EVENT_AGE_HOURS,
    SIGNAL_WEIGHTS,
    TASTE_BOOTSTRAP_EVENTS,
)
from app.modules.post.data.taste_models import PostInteractionEvent
from app.modules.post.presentation.taste_schemas import InteractionEventItem
from app.modules.post.recommendation.session_taste import taste_service
from app.modules.post.data.models import Post
from app.modules.profile.data.models import Business, Profile
from app.recommendation.amplify import write_post_signals
from app.recommendation.session_taste import ActionType

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Signal helpers
# ---------------------------------------------------------------------------

def classify_dwell(value_ms: int) -> str:
    """Bucket a raw dwell_ms value into one of the four dwell signal keys."""
    if value_ms < DWELL_BOUNCE_MS:
        return "dwell_bounce"
    if value_ms < DWELL_SHORT_MS:
        return "dwell_short"
    if value_ms < DWELL_LONG_MS:
        return "dwell_medium"
    return "dwell_long"


def derive_signal(event_type: str, value_ms: int | None) -> tuple[float, float]:
    """
    Returns (positive_delta, negative_delta) for a given event.
    Dwell events are classified first; all others look up directly by event_type.
    """
    if event_type == "dwell" and value_ms is not None:
        key = classify_dwell(value_ms)
    else:
        key = event_type
    return SIGNAL_WEIGHTS.get(key, (0.0, 0.0))


def _classify_action(event_type: str, value_ms: int | None) -> ActionType | None:
    """
    Maps a raw client event into a shared session-taste ActionType, reusing
    this module's own dwell-bucket boundaries (classify_dwell above).
    Returns None for anything that doesn't map to a valid ActionType member.
    """
    if event_type == "dwell" and value_ms is not None:
        key = classify_dwell(value_ms)
    else:
        key = event_type
    try:
        return ActionType(key)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Batch write path (client events)
# ---------------------------------------------------------------------------

def process_interaction_batch(
    repo,
    profile_id: int,
    events: list[InteractionEventItem],
    rc: redis.Redis | None = None,
) -> dict:
    """
    Processes a client-submitted batch of interaction events.

    1. Drops events older than MAX_EVENT_AGE_HOURS.
    2. Drops events referencing non-existent post_ids.
    3. Caps dwell value_ms at DWELL_VALUE_CAP_MS.
    4. Bulk-inserts valid events into post_interaction_events (processed_at=NULL).
    5. For dwell events with value_ms >= DWELL_SEEN_MS: upserts into seen_posts.
    6. After commit: fires a shared session-taste signal (category/commodity/
       city/state) per accepted event, best-effort.
    """
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(hours=MAX_EVENT_AGE_HOURS)

    raw_post_ids = list({e.post_id for e in events})
    post_meta: dict[int, tuple[int, int, str | None, str | None]] = (
        repo.post_taste_meta(raw_post_ids)
    )
    valid_post_ids: set[int] = set(post_meta.keys())

    rows: list[PostInteractionEvent] = []
    seen_post_ids: list[int] = []
    signal_events: list[tuple[int, str, int | None]] = []
    dropped = 0

    for event in events:
        occurred = event.occurred_at
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=timezone.utc)

        if occurred < stale_cutoff:
            dropped += 1
            continue

        if event.post_id not in valid_post_ids:
            dropped += 1
            continue

        value_ms = None
        if event.value_ms is not None:
            value_ms = min(event.value_ms, DWELL_VALUE_CAP_MS)

        rows.append(PostInteractionEvent(
            profile_id=profile_id,
            post_id=event.post_id,
            event_type=event.event_type,
            value_ms=value_ms,
            occurred_at=occurred,
            created_at=now,
            processed_at=None,
        ))
        signal_events.append((event.post_id, event.event_type, value_ms))

        if (
            event.event_type == "dwell"
            and value_ms is not None
            and value_ms >= DWELL_SEEN_MS
        ):
            seen_post_ids.append(event.post_id)

    if rows:
        repo.bulk_add_events(rows)

    if seen_post_ids:
        repo.mark_posts_seen(profile_id, seen_post_ids, now)

    repo.commit()

    for post_id, event_type, value_ms in signal_events:
        category_id, commodity_id, post_city, post_state = post_meta[post_id]
        category = CATEGORY_NAMES.get(category_id)
        action = _classify_action(event_type, value_ms)
        if action is None:
            continue
        write_post_signals(rc, profile_id, category, commodity_id, action, city=post_city, state=post_state)

    return {"accepted": len(rows), "dropped": dropped}


# ---------------------------------------------------------------------------
# Server-generated revisit event
# ---------------------------------------------------------------------------

def record_revisit_event(repo, profile_id: int, post_id: int) -> None:
    """
    Called from post/service._record_view() when the unique constraint on
    post_views fires — the user has opened this post before.

    1. Logs a revisit event to post_interaction_events (processed_at set to now
       since taste is updated synchronously here — no async job needed).
    2. Updates category taste with revisit signal weight.
    """
    now = datetime.now(timezone.utc)
    try:
        repo.add_interaction_events([PostInteractionEvent(
            profile_id=profile_id,
            post_id=post_id,
            event_type="revisit",
            value_ms=None,
            occurred_at=now,
            created_at=now,
            processed_at=now,      # handled synchronously — no async job pickup needed
        )])
        repo.commit()
    except Exception:
        repo.rollback()
        return

    # Update taste — look up post for category + commodity + author
    post = repo.get_post_for_taste(post_id)
    if post:
        try:
            record_interaction(
                repo, profile_id,
                post.category_id, "revisit",
                post.commodity_id, post.profile_id,
            )
        except Exception:
            log.exception("revisit taste update failed for profile %s on post %s", profile_id, post_id)


# ---------------------------------------------------------------------------
# Synchronous taste update (like / save / comment / share / revisit)
# ---------------------------------------------------------------------------

# Categories taste is tracked for. Anything outside this set is ignored rather
# than written as an unknown dimension key.
TASTE_CATEGORIES = frozenset({"market_update", "deal_req", "discussion", "knowledge"})


def record_interaction(
    repo,
    profile_id: int,
    category_id: int,
    signal_type: str = "like",
    commodity_id: int | None = None,
    author_profile_id: int | None = None,
) -> None:
    """
    Applies a weighted taste delta for a synchronous interaction signal
    (like / save / comment / share / revisit).

    Writes user_post_taste — the single authoritative taste store, read by both
    the recommendation feed and the following feed.
        dimensions written: category, commodity (if provided),
        author (if provided, signal strong enough, and author != viewer)
    """
    category = CATEGORY_NAMES.get(category_id)
    if not category:
        return

    if category not in TASTE_CATEGORIES:
        return

    pos_delta, neg_delta = derive_signal(signal_type, None)
    if pos_delta <= 0:
        return

    # A deleted profile has no taste to record (the legacy write used to be the
    # thing that caught this).
    if not repo.profile_exists(profile_id):
        return

    # user_post_taste is the one taste store — see get_taste_weights().
    taste_service.update_taste(
            repo, profile_id, "category", category, pos_delta, neg_delta)

    if commodity_id is not None:
        taste_service.update_taste(
            repo, profile_id, "commodity", str(commodity_id), pos_delta, neg_delta)

    # Author affinity: only for high-confidence signals; never self-interaction
    if (
        author_profile_id is not None
        and author_profile_id != profile_id
        and pos_delta >= AUTHOR_TASTE_MIN_DELTA
    ):
        taste_service.update_taste(
            repo, profile_id, "author", str(author_profile_id), pos_delta, neg_delta)

    repo.commit()
