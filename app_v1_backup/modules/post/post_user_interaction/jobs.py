"""
Post User Interaction background jobs.

run_taste_update_job()      – every 15 min: processes unprocessed dwell events.
                              Positive deltas → category/commodity/author taste.
                              Bounce (< 2 s) → negative category/commodity taste.

run_ignore_detection_job()  – daily: finds (profile, post) pairs with N+ impressions
                              and zero engagement; applies negative taste and marks
                              impression events processed so each pair is actioned once.
"""
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.post.post_user_interaction.constants import (
    AUTHOR_TASTE_MIN_DELTA,
    CATEGORY_NAMES,
    DWELL_BOUNCE_MS,
    IGNORE_NEG_DELTA,
    REPEATED_IGNORE_THRESHOLD,
)
from app.modules.post.post_user_interaction.models import (
    PostInteractionEvent,
    UserTasteProfile,
)
from app.modules.post.post_user_interaction.service import (
    _CATEGORY_COL_MAP,
    _to_int_delta,
    derive_signal,
)
from app.modules.post.post_user_interaction import taste_service
from app.modules.post.models import Post

_BATCH_SIZE        = 500   # max passive events per taste-update run
_IGNORE_BATCH_SIZE = 500  # max (profile, post) pairs per ignore-detection run

# Event types processed by run_taste_update_job.
# dwell   — needs duration classification (bounce / short / medium / long)
# open_*  — fixed positive weight, no value_ms needed
# link_click — fixed positive weight, no value_ms needed
_PASSIVE_EVENT_TYPES = frozenset({
    "dwell",
    "open_read_more",
    "open_carousel",
    "open_comments",
    "link_click",
})


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _acc(
    upt_deltas: dict,
    profile_id: int,
    dim_type: str,
    dim_key: str,
    pos: float,
    neg: float,
    count: int = 1,
) -> None:
    """Accumulate a (pos, neg, count) delta into the upt_deltas dictionary."""
    key = (profile_id, dim_type, dim_key)
    if key not in upt_deltas:
        upt_deltas[key] = [0.0, 0.0, 0]    # [pos_total, neg_total, event_count]
    upt_deltas[key][0] += pos
    upt_deltas[key][1] += neg
    upt_deltas[key][2] += count


# ---------------------------------------------------------------------------
# Job 1: Dwell taste update (every 15 min)
# ---------------------------------------------------------------------------

def run_taste_update_job(db: Session) -> dict:
    """
    Processes the oldest unprocessed dwell events (up to _BATCH_SIZE per run).

    Positive dwells (>= DWELL_BOUNCE_MS):
      - user_taste_profiles  (legacy integer counters, active reranker read path)
      - user_post_taste      category, commodity, author (where applicable)

    Bounce dwells (< DWELL_BOUNCE_MS):
      - user_post_taste only  category, commodity — negative delta
      - user_taste_profiles has no negative_score column; skip legacy write

    impressions / open_* / link_click are not processed here.
    All fetched dwell events are marked processed_at = now.
    """
    now = datetime.now(timezone.utc)

    events: list[PostInteractionEvent] = (
        db.query(PostInteractionEvent)
        .filter(
            PostInteractionEvent.event_type.in_(_PASSIVE_EVENT_TYPES),
            PostInteractionEvent.processed_at.is_(None),
        )
        .order_by(PostInteractionEvent.id)
        .limit(_BATCH_SIZE)
        .all()
    )

    if not events:
        return {"processed": 0, "taste_updates": 0}

    # Bulk-fetch category, commodity, author for all referenced posts
    post_ids = list({e.post_id for e in events})
    post_meta: dict[int, tuple[int, int, int]] = {
        row[0]: (row[1], row[2], row[3])
        for row in db.query(Post.id, Post.category_id, Post.commodity_id, Post.profile_id)
        .filter(Post.id.in_(post_ids))
        .all()
    }

    # ── Accumulate deltas ─────────────────────────────────────────────────────
    # Legacy: { profile_id → { col_name → int_delta } }
    utp_col_deltas: dict[int, dict[str, int]] = {}
    utp_event_counts: dict[int, int] = {}

    # Phase 3/4/5: { (profile_id, dim_type, dim_key) → [pos, neg, count] }
    upt_deltas: dict[tuple[int, str, str], list] = {}

    for event in events:
        meta = post_meta.get(event.post_id)
        if not meta:
            continue                        # post deleted — skip

        category_id, commodity_id, author_profile_id = meta
        category = CATEGORY_NAMES.get(category_id)
        col = _CATEGORY_COL_MAP.get(category) if category else None
        if not col:
            continue

        pid = event.profile_id

        # ── Dwell ─────────────────────────────────────────────────────────────
        if event.event_type == "dwell":
            if event.value_ms is None:
                continue                    # malformed row — skip, will be marked processed

            pos_delta, neg_delta = derive_signal("dwell", event.value_ms)
            is_bounce = event.value_ms < DWELL_BOUNCE_MS

            if is_bounce:
                if neg_delta > 0:
                    _acc(upt_deltas, pid, "category", category, 0.0, neg_delta)
                    if commodity_id:
                        _acc(upt_deltas, pid, "commodity", str(commodity_id), 0.0, neg_delta)
                continue

            int_delta = _to_int_delta(pos_delta)
            if pos_delta <= 0:
                continue

            if int_delta > 0:
                cols = utp_col_deltas.setdefault(pid, {})
                cols[col] = cols.get(col, 0) + int_delta
            utp_event_counts[pid] = utp_event_counts.get(pid, 0) + 1

            _acc(upt_deltas, pid, "category", category, pos_delta, 0.0)
            if commodity_id:
                _acc(upt_deltas, pid, "commodity", str(commodity_id), pos_delta, 0.0)

            if (
                pos_delta >= AUTHOR_TASTE_MIN_DELTA
                and author_profile_id
                and author_profile_id != pid
            ):
                _acc(upt_deltas, pid, "author", str(author_profile_id), pos_delta, 0.0)

        # ── Open events & link_click ──────────────────────────────────────────
        # open_read_more=1.5  open_carousel=1.0  open_comments=1.5  link_click=2.0
        else:
            pos_delta, _ = derive_signal(event.event_type, None)
            if pos_delta <= 0:
                continue

            int_delta = _to_int_delta(pos_delta)

            if int_delta > 0:
                cols = utp_col_deltas.setdefault(pid, {})
                cols[col] = cols.get(col, 0) + int_delta
            utp_event_counts[pid] = utp_event_counts.get(pid, 0) + 1

            _acc(upt_deltas, pid, "category", category, pos_delta, 0.0)
            if commodity_id:
                _acc(upt_deltas, pid, "commodity", str(commodity_id), pos_delta, 0.0)

            # Author affinity only for link_click (2.0 ≥ threshold); open_* are below 2.0
            if (
                pos_delta >= AUTHOR_TASTE_MIN_DELTA
                and author_profile_id
                and author_profile_id != pid
            ):
                _acc(upt_deltas, pid, "author", str(author_profile_id), pos_delta, 0.0)

    # ── Apply legacy deltas ───────────────────────────────────────────────────
    taste_updates = 0
    for profile_id, col_deltas in utp_col_deltas.items():
        taste = db.query(UserTasteProfile).filter(
            UserTasteProfile.profile_id == profile_id
        ).first()
        if taste is None:
            continue                        # profile created on first explicit interaction
        for col, delta in col_deltas.items():
            setattr(taste, col, getattr(taste, col) + delta)
        taste.total_events += utp_event_counts.get(profile_id, 0)
        taste_updates += 1

    # ── Apply Phase 3/4/5 deltas ─────────────────────────────────────────────
    for (profile_id, dim_type, dim_key), (pos_d, neg_d, cnt) in upt_deltas.items():
        if pos_d > 0 or neg_d > 0:
            taste_service.update_taste(
                db, profile_id, dim_type, dim_key, pos_d, neg_d, cnt
            )

    # ── Mark all fetched dwell events processed ───────────────────────────────
    event_ids = [e.id for e in events]
    db.query(PostInteractionEvent).filter(
        PostInteractionEvent.id.in_(event_ids)
    ).update({"processed_at": now}, synchronize_session=False)

    db.commit()
    return {"processed": len(events), "taste_updates": taste_updates}


# ---------------------------------------------------------------------------
# Job 2: Repeated-ignore detection (daily)
# ---------------------------------------------------------------------------

def run_ignore_detection_job(db: Session) -> dict:
    """
    Finds (profile_id, post_id) pairs where:
      - impression_count >= REPEATED_IGNORE_THRESHOLD
      - zero engagement events (dwell, open_*, revisit)
      - at least one impression event is still unprocessed

    For each such pair:
      - Applies IGNORE_NEG_DELTA to category and commodity in user_post_taste
      - Marks all impression events for that pair as processed_at = now
        (ensures each pair is only actioned once)

    "Engagement" includes bounce-dwell events — if the user opened the post
    even briefly, it is not considered an ignore.
    """
    now = datetime.now(timezone.utc)

    rows = db.execute(
        text("""
            SELECT profile_id, post_id
            FROM post_interaction_events
            GROUP BY profile_id, post_id
            HAVING
                SUM(CASE WHEN event_type = 'impression' THEN 1 ELSE 0 END)
                    >= :threshold
                AND SUM(CASE WHEN event_type IN (
                        'dwell', 'open_read_more', 'open_carousel',
                        'open_comments', 'revisit'
                    ) THEN 1 ELSE 0 END) = 0
                AND SUM(CASE WHEN event_type = 'impression'
                             AND processed_at IS NULL THEN 1 ELSE 0 END) > 0
            ORDER BY profile_id, post_id
            LIMIT :limit
        """),
        {"threshold": REPEATED_IGNORE_THRESHOLD, "limit": _IGNORE_BATCH_SIZE},
    ).mappings().all()

    if not rows:
        return {"pairs_detected": 0, "taste_updates": 0}

    ignore_pairs: list[tuple[int, int]] = [
        (r["profile_id"], r["post_id"]) for r in rows
    ]

    # Bulk-fetch post metadata
    post_ids = list({ppid for _, ppid in ignore_pairs})
    post_meta: dict[int, tuple[int, int]] = {
        row[0]: (row[1], row[2])
        for row in db.query(Post.id, Post.category_id, Post.commodity_id)
        .filter(Post.id.in_(post_ids))
        .all()
    }

    # Apply negative taste deltas
    taste_updates = 0
    for profile_id, post_id in ignore_pairs:
        meta = post_meta.get(post_id)
        if not meta:
            continue
        category_id, commodity_id = meta
        category = CATEGORY_NAMES.get(category_id)
        if not category:
            continue

        taste_service.update_taste(
            db, profile_id, "category", category, 0.0, IGNORE_NEG_DELTA
        )
        if commodity_id:
            taste_service.update_taste(
                db, profile_id, "commodity", str(commodity_id), 0.0, IGNORE_NEG_DELTA
            )
        taste_updates += 1

    # Mark impression events for all detected pairs as processed
    # Both values are DB integers — no injection risk from string format.
    pairs_str = ",".join(f"({pid},{ppid})" for pid, ppid in ignore_pairs)
    db.execute(
        text(f"""
            UPDATE post_interaction_events
            SET processed_at = :now
            WHERE event_type = 'impression'
              AND processed_at IS NULL
              AND (profile_id, post_id) IN ({pairs_str})
        """),
        {"now": now},
    )

    db.commit()
    return {"pairs_detected": len(ignore_pairs), "taste_updates": taste_updates}
