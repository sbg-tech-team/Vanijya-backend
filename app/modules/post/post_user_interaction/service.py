"""
Post User Interaction Service

Write paths:
  process_interaction_batch()  – batch endpoint handler (impression, dwell, open_*, link_click)
  record_revisit_event()       – called from post/service._record_view() on duplicate view
  record_interaction()         – synchronous taste update on like / save / comment / share

Read path:
  get_taste_for_feed()         – taste weights for the recommendation reranker

Signal helpers (used by jobs.py):
  classify_dwell()             – bucket a dwell_ms value into a signal key
  derive_signal()              – (positive_delta, negative_delta) from an event
"""
from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.post.post_user_interaction.constants import (
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
from app.modules.post.post_user_interaction.models import (
    PostInteractionEvent,
    UserTasteProfile,
)
from app.modules.post.post_user_interaction.schemas import InteractionEventItem
from app.modules.post.post_user_interaction import taste_service
from app.modules.post.models import Post
from app.modules.profile.models import Profile


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


def _to_int_delta(value: float) -> int:
    """
    Convert a float signal weight to an integer for storage in the current
    Integer columns of user_taste_profiles.  Uses 'round half up' (not
    Python's default banker's rounding) so 0.5 → 1 and 3.5 → 4.
    Phase 3 will switch to Float columns and this helper becomes unnecessary.
    """
    return int(value + 0.5)


# ---------------------------------------------------------------------------
# Batch write path (client events)
# ---------------------------------------------------------------------------

def process_interaction_batch(
    db: Session,
    profile_id: int,
    events: list[InteractionEventItem],
) -> dict:
    """
    Processes a client-submitted batch of interaction events.

    1. Drops events older than MAX_EVENT_AGE_HOURS.
    2. Drops events referencing non-existent post_ids.
    3. Caps dwell value_ms at DWELL_VALUE_CAP_MS.
    4. Bulk-inserts valid events into post_interaction_events (processed_at=NULL).
    5. For dwell events with value_ms >= DWELL_SEEN_MS: upserts into seen_posts.
    """
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(hours=MAX_EVENT_AGE_HOURS)

    raw_post_ids = list({e.post_id for e in events})
    valid_post_ids: set[int] = {
        row[0]
        for row in db.query(Post.id).filter(Post.id.in_(raw_post_ids)).all()
    }

    rows: list[PostInteractionEvent] = []
    seen_post_ids: list[int] = []
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

        if (
            event.event_type == "dwell"
            and value_ms is not None
            and value_ms >= DWELL_SEEN_MS
        ):
            seen_post_ids.append(event.post_id)

    if rows:
        db.bulk_save_objects(rows)

    if seen_post_ids:
        db.execute(
            text("""
                INSERT INTO seen_posts (profile_id, post_id, seen_at)
                SELECT :profile_id, unnest(CAST(:post_ids AS int[])), :seen_at
                ON CONFLICT (profile_id, post_id) DO NOTHING
            """),
            {
                "profile_id": profile_id,
                "post_ids": "{" + ",".join(str(p) for p in seen_post_ids) + "}",
                "seen_at": now,
            },
        )

    db.commit()
    return {"accepted": len(rows), "dropped": dropped}


# ---------------------------------------------------------------------------
# Server-generated revisit event
# ---------------------------------------------------------------------------

def record_revisit_event(db: Session, profile_id: int, post_id: int) -> None:
    """
    Called from post/service._record_view() when the unique constraint on
    post_views fires — the user has opened this post before.

    1. Logs a revisit event to post_interaction_events (processed_at set to now
       since taste is updated synchronously here — no async job needed).
    2. Updates category taste with revisit signal weight.
    """
    now = datetime.now(timezone.utc)
    try:
        db.add(PostInteractionEvent(
            profile_id=profile_id,
            post_id=post_id,
            event_type="revisit",
            value_ms=None,
            occurred_at=now,
            created_at=now,
            processed_at=now,      # handled synchronously — no async job pickup needed
        ))
        db.commit()
    except Exception:
        db.rollback()
        return

    # Update taste — look up post for category + commodity + author
    post = db.query(Post).filter(Post.id == post_id).first()
    if post:
        try:
            record_interaction(
                db, profile_id,
                post.category_id, "revisit",
                post.commodity_id, post.profile_id,
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Synchronous taste update (like / save / comment / share / revisit)
# ---------------------------------------------------------------------------

_CATEGORY_COL_MAP = {
    "market_update": "market_update_count",
    "deal_req":      "deal_req_count",
    "discussion":    "discussion_count",
    "knowledge":     "knowledge_count",
}


def record_interaction(
    db: Session,
    profile_id: int,
    category_id: int,
    signal_type: str = "like",
    commodity_id: int | None = None,
    author_profile_id: int | None = None,
) -> None:
    """
    Applies a weighted taste delta for a synchronous interaction signal
    (like / save / comment / share / revisit).

    Writes to two tables:
    - user_taste_profiles  (legacy Integer counters, active reranker read path)
    - user_post_taste      (new Float row-per-dimension store, Phase 3+)
        dimensions written: category, commodity (if provided),
        author (if provided, signal strong enough, and author != viewer)

    total_events on user_taste_profiles is incremented by 1 per call — it
    counts interaction events, not weighted scores.
    """
    category = CATEGORY_NAMES.get(category_id)
    if not category:
        return

    col = _CATEGORY_COL_MAP.get(category)
    if not col:
        return

    pos_delta, neg_delta = derive_signal(signal_type, None)
    int_delta = _to_int_delta(pos_delta)
    if int_delta <= 0 and pos_delta <= 0:
        return

    # ── Legacy write: user_taste_profiles ────────────────────────────────────
    taste = db.query(UserTasteProfile).filter(
        UserTasteProfile.profile_id == profile_id
    ).first()

    if taste is None:
        profile = db.query(Profile).filter(Profile.id == profile_id).first()
        if not profile:
            return
        defaults = DEFAULT_TASTE.get(profile.role_id, DEFAULT_TASTE[1])
        taste = UserTasteProfile(
            profile_id=profile_id,
            market_update_count=defaults["market_update"],
            deal_req_count=defaults["deal_req"],
            discussion_count=defaults["discussion"],
            knowledge_count=defaults["knowledge"],
            total_events=0,
        )
        db.add(taste)
        db.flush()

    if int_delta > 0:
        setattr(taste, col, getattr(taste, col) + int_delta)
    taste.total_events += 1

    # ── Phase 3/4 write: user_post_taste ─────────────────────────────────────
    taste_service.update_taste(db, profile_id, "category", category, pos_delta, neg_delta)

    if commodity_id is not None:
        taste_service.update_taste(db, profile_id, "commodity", str(commodity_id), pos_delta, neg_delta)

    # Author affinity: only for high-confidence signals; never self-interaction
    if (
        author_profile_id is not None
        and author_profile_id != profile_id
        and pos_delta >= AUTHOR_TASTE_MIN_DELTA
    ):
        taste_service.update_taste(db, profile_id, "author", str(author_profile_id), pos_delta, neg_delta)

    db.commit()


# ---------------------------------------------------------------------------
# Taste read (called by the recommendation engine)
# ---------------------------------------------------------------------------

def get_taste_for_feed(db: Session, profile_id: int, role_id: int) -> dict[str, int]:
    """
    Returns category interaction counts for the recommendation reranker.

    Below TASTE_BOOTSTRAP_EVENTS the returned counts are a confidence-blended
    mix of the user's actual interactions and the role-seeded defaults,
    preventing over-fitting to the first 1–2 interactions.
    """
    taste = db.query(UserTasteProfile).filter(
        UserTasteProfile.profile_id == profile_id
    ).first()

    defaults = DEFAULT_TASTE.get(role_id, DEFAULT_TASTE[1])

    if taste is None:
        return defaults

    learned = {
        "market_update": taste.market_update_count,
        "deal_req":      taste.deal_req_count,
        "discussion":    taste.discussion_count,
        "knowledge":     taste.knowledge_count,
    }

    if taste.total_events >= TASTE_BOOTSTRAP_EVENTS:
        return learned

    confidence = taste.total_events / TASTE_BOOTSTRAP_EVENTS
    return {
        cat: int(confidence * learned[cat] + (1 - confidence) * defaults[cat])
        for cat in learned
    }
