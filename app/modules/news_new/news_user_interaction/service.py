from datetime import datetime, timezone, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.news_new.news_user_interaction.constants import (
    DWELL_BOUNCE_MS,
    DWELL_MEDIUM_MS,
    DWELL_SEEN_MS,
    DWELL_SHORT_MS,
    DWELL_VALUE_CAP_MS,
    MAX_EVENT_AGE_HOURS,
    SIGNAL_WEIGHTS,
)
from app.modules.news_new.news_user_interaction.models import (
    NewsArticleStats,
    NewsInteractionEvent,
    NewsLike,
    NewsSave,
    NewsShare,
    NewsView,
)
from app.modules.news_new.news_user_interaction.schemas import NewsInteractionEventItem, NewsSendRequest
from app.modules.news_new.news_user_interaction import taste_service
from app.modules.news_new.ingestion.models import RawArticle


def classify_dwell(value_ms: int) -> str:
    if value_ms < DWELL_BOUNCE_MS:
        return "dwell_bounce"
    if value_ms < DWELL_SHORT_MS:
        return "dwell_short"
    if value_ms < DWELL_MEDIUM_MS:
        return "dwell_medium"
    return "dwell_long"


def derive_signal(event_type: str, value_ms: int | None = None) -> tuple[float, float]:
    if event_type == "dwell" and value_ms is not None:
        key = classify_dwell(value_ms)
    else:
        key = event_type
    return SIGNAL_WEIGHTS.get(key, (0.0, 0.0))


def process_interaction_batch(
    db: Session,
    profile_id: int,
    events: list[NewsInteractionEventItem],
) -> dict:
    """
    Accepts a client event batch. Drops stale events and events for unknown
    articles. Upserts NewsView and fires revisit events on open_article.
    Bulk-inserts valid events; caller does NOT need to commit separately.
    """
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(hours=MAX_EVENT_AGE_HOURS)

    raw_article_ids = list({e.article_id for e in events})
    valid_ids: set[UUID] = {
        row[0]
        for row in db.execute(
            select(RawArticle.id).where(RawArticle.id.in_(raw_article_ids))
        ).all()
    }

    rows: list[NewsInteractionEvent] = []
    dropped = 0

    for event in events:
        occurred = event.occurred_at
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=timezone.utc)

        if occurred < stale_cutoff:
            dropped += 1
            continue

        if event.article_id not in valid_ids:
            dropped += 1
            continue

        value_ms = None
        if event.value_ms is not None:
            value_ms = min(event.value_ms, DWELL_VALUE_CAP_MS)

        rows.append(NewsInteractionEvent(
            profile_id=profile_id,
            article_id=event.article_id,
            event_type=event.event_type,
            value_ms=value_ms,
            occurred_at=occurred,
        ))

        if event.event_type == "open_article":
            is_revisit = upsert_view(db, profile_id, event.article_id)
            if is_revisit:
                _record_revisit_event(db, profile_id, event.article_id)

    if rows:
        db.bulk_save_objects(rows)

    db.commit()
    return {"accepted": len(rows), "dropped": dropped}


def upsert_view(db: Session, profile_id: int, article_id: UUID) -> bool:
    """
    Creates or updates the NewsView row.
    Returns True if this is a revisit (view already existed).
    Does NOT commit — caller owns the transaction.
    """
    view = get_view(db, profile_id, article_id)
    if view is None:
        db.add(NewsView(profile_id=profile_id, article_id=article_id))
        return False

    view.view_count += 1
    view.last_viewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(view)
    return True


def _record_revisit_event(db: Session, profile_id: int, article_id: UUID) -> None:
    """
    Server-generated revisit event. Inserts a processed event (no async job
    needed) and synchronously updates category taste.
    """
    from app.modules.news_new.intelligence.models import EnrichedArticle

    now = datetime.now(timezone.utc)
    db.add(NewsInteractionEvent(
        profile_id=profile_id,
        article_id=article_id,
        event_type="revisit",
        occurred_at=now,
        processed_at=now,
    ))

    factor = db.execute(
        select(EnrichedArticle.primary_factor).where(EnrichedArticle.raw_article_id == article_id)
    ).scalar_one_or_none()
    if factor:
        pos, neg = SIGNAL_WEIGHTS.get("revisit", (0.0, 0.0))
        taste_service.update_taste(db, profile_id, "category", factor, pos, neg)


def toggle_like(db: Session, profile_id: int, article_id: UUID) -> bool:
    """Toggle like. Returns the new is_liked state."""
    existing = db.execute(
        select(NewsLike).where(
            NewsLike.profile_id == profile_id,
            NewsLike.article_id == article_id,
        )
    ).scalar_one_or_none()

    if existing:
        db.delete(existing)
        _adjust_stats(db, article_id, "like_count", -1)
        db.commit()
        return False

    db.add(NewsLike(profile_id=profile_id, article_id=article_id))
    _adjust_stats(db, article_id, "like_count", 1)
    _taste_from_article(db, profile_id, article_id, "like")
    db.commit()
    return True


def toggle_save(db: Session, profile_id: int, article_id: UUID) -> bool:
    """Toggle save. Returns the new is_saved state."""
    existing = db.execute(
        select(NewsSave).where(
            NewsSave.profile_id == profile_id,
            NewsSave.article_id == article_id,
        )
    ).scalar_one_or_none()

    if existing:
        db.delete(existing)
        _adjust_stats(db, article_id, "save_count", -1)
        db.commit()
        return False

    db.add(NewsSave(profile_id=profile_id, article_id=article_id))
    _adjust_stats(db, article_id, "save_count", 1)
    _taste_from_article(db, profile_id, article_id, "save")
    db.commit()
    return True


def record_share(db: Session, profile_id: int, article_id: UUID, platform: str | None = None) -> None:
    db.add(NewsShare(profile_id=profile_id, article_id=article_id, platform=platform))
    _adjust_stats(db, article_id, "share_count", 1)
    _taste_from_article(db, profile_id, article_id, "share_tap")
    db.commit()


def _taste_from_article(db: Session, profile_id: int, article_id: UUID, signal_type: str) -> None:
    """Look up article's primary_factor from EnrichedArticle and write a taste delta."""
    from app.modules.news_new.intelligence.models import EnrichedArticle

    factor = db.execute(
        select(EnrichedArticle.primary_factor).where(EnrichedArticle.raw_article_id == article_id)
    ).scalar_one_or_none()
    if factor:
        pos, neg = SIGNAL_WEIGHTS.get(signal_type, (0.0, 0.0))
        taste_service.update_taste(db, profile_id, "category", factor, pos, neg)


# ── Read helpers ─────────────────────────────────────────────────────────────


def get_view(db: Session, profile_id: int, article_id: UUID) -> NewsView | None:
    return db.execute(
        select(NewsView).where(
            NewsView.profile_id == profile_id,
            NewsView.article_id == article_id,
        )
    ).scalar_one_or_none()


def get_article_stats(db: Session, article_id: UUID) -> NewsArticleStats | None:
    return db.execute(
        select(NewsArticleStats).where(NewsArticleStats.article_id == article_id)
    ).scalar_one_or_none()


def _adjust_stats(db: Session, article_id: UUID, field: str, delta: int) -> None:
    stats = get_article_stats(db, article_id)
    if stats is None:
        stats = NewsArticleStats(article_id=article_id)
        db.add(stats)
        db.flush()
    current = getattr(stats, field, 0) or 0
    setattr(stats, field, max(0, current + delta))
    stats.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(stats)


# ── In-app share ──────────────────────────────────────────────────────────────


class ArticleNotFoundError(Exception):
    pass


def send_article(
    db: Session,
    article_id: UUID,
    user_id: UUID,
    profile_id: int,
    payload: NewsSendRequest,
) -> dict:
    """
    Full in-app share of a news article:
      1. Validate article exists.
      2. Deliver as a 'news_article' chat message to each selected DM / group.
         Silently skips recipients that fail permission checks (partial delivery).
      3. Increment share_count once regardless of recipient count.
      4. Return share_count + raw delivery lists so the router can emit WebSocket events.
    """
    from app.modules.chat.data.repository import ChatRepository
    from app.modules.chat.domain.entities import ConvStatus

    article = db.execute(
        select(RawArticle).where(RawArticle.id == article_id)
    ).scalar_one_or_none()
    if article is None:
        raise ArticleNotFoundError(f"Article {article_id} not found.")

    chat_repo = ChatRepository(db)

    dm_deliveries: list[tuple] = []
    for conv_id in payload.dm_conversation_ids:
        guard = chat_repo.get_conv_send_info(conv_id, user_id)
        if guard and guard.status == ConvStatus.ACTIVE:
            msg = chat_repo.save_message(
                context_type="dm",
                context_id=conv_id,
                sender_id=user_id,
                message_type="news_article",
                article_id=article_id,
                body=payload.caption,
            )
            dm_deliveries.append((guard.receiver_id, msg))

    group_deliveries: list[tuple] = []
    for group_id in payload.group_ids:
        chat_perm = chat_repo.get_group_chat_perm(group_id)
        member_role = chat_repo.get_group_member_role(group_id, user_id)
        is_frozen = chat_repo.is_group_member_frozen(group_id, user_id)
        if (chat_perm and member_role and not is_frozen
                and (chat_perm == "all_members" or member_role == "admin")):
            msg = chat_repo.save_message(
                context_type="group",
                context_id=group_id,
                sender_id=user_id,
                message_type="news_article",
                article_id=article_id,
                body=payload.caption,
            )
            group_deliveries.append((group_id, msg))

    db.add(NewsShare(profile_id=profile_id, article_id=article_id))
    _adjust_stats(db, article_id, "share_count", 1)
    db.commit()

    try:
        _taste_from_article(db, profile_id, article_id, "share_tap")
        db.commit()
    except Exception:
        pass

    stats = get_article_stats(db, article_id)
    share_count = stats.share_count if stats else 0

    return {
        "share_count": share_count,
        "dm_deliveries": dm_deliveries,
        "group_deliveries": group_deliveries,
    }
