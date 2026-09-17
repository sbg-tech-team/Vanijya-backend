"""
Interaction processing use case.

Ported from app_v1_backup/modules/news_new/news_user_interaction/service.py.

Client event batch flow (POST /interactions/batch):
  1. Drop stale events (> MAX_EVENT_AGE_HOURS) and events for unknown articles.
  2. For each open_article event: upsert_view -> is_revisit?
       -> True: synthesise a server-generated "revisit" event, persist +
          session-taste update.
  3. Bulk insert all validated events, commit.
  4. AFTER commit: fire-and-forget a Redis session-taste signal (commodity +
     city + state) for every accepted event. Regular client events (impression,
     dwell, open_article-first-time, share_tap) get ONLY this session signal -
     no persistent UserNewsTaste write. Only "revisit" also writes persistent
     taste (category dimension), matching app_v1_backup exactly.

Synchronous actions (like / save / share) each commit independently, and each
writes BOTH a persistent UserNewsTaste "category" delta and a Redis session
signal.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

import redis

from app.modules.news.domain.entities import NewsInteractionEvent
from app.modules.news.domain.exceptions import ArticleNotFoundError
from app.modules.news.domain.interfaces.repository import INewsRepository
from app.modules.news.domain.value_objects import CLIENT_EVENT_TYPES
from app.recommendation.amplify import commodity_ids_for, write_news_signals
from app.recommendation.session_taste import ActionType

log = logging.getLogger(__name__)

# -- Interaction signal constants (ported from app_v1_backup) ------------------

MAX_EVENT_AGE_HOURS = 2
_DWELL_BOUNCE_MS = 3_000
_DWELL_SHORT_MS = 15_000
_DWELL_MEDIUM_MS = 60_000
_DWELL_VALUE_CAP_MS = 600_000
BATCH_MAX_EVENTS = 200

_SIGNAL_WEIGHTS: dict[str, tuple[float, float]] = {
    "impression":   (0.1, 0.0),
    "dwell_bounce": (0.0, 0.5),
    "dwell_short":  (0.5, 0.0),
    "dwell_medium": (2.0, 0.0),
    "dwell_long":   (3.5, 0.0),
    "open_article": (1.5, 0.0),
    "share_tap":    (2.0, 0.0),
    "like":         (3.0, 0.0),
    "save":         (5.0, 0.0),
    "share":        (4.0, 0.0),
    "revisit":      (6.0, 0.0),
}

# Maps News' own client event-type vocabulary onto the shared session-taste
# ActionType vocabulary where the names differ.
_EVENT_ALIAS = {"open_article": "open_read_more", "share_tap": "share"}


class RecordInteractionUseCase:

    def __init__(self, repo: INewsRepository) -> None:
        self._repo = repo

    # -- Bulk event batch (client-submitted) -----------------------------------

    def process_event_batch(
        self,
        profile_id: int,
        raw_events: list[dict],
        rc: redis.Redis | None = None,
    ) -> dict:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        cutoff = now - timedelta(hours=MAX_EVENT_AGE_HOURS)

        candidates: list[dict] = [
            e for e in raw_events
            if e.get("event_type") in CLIENT_EVENT_TYPES
            and _parse_occurred_at(e.get("occurred_at"), now) >= cutoff
        ]

        article_ids = {UUID(e["article_id"]) for e in candidates if e.get("article_id")}
        valid_ids = self._repo.filter_valid_article_ids(list(article_ids))
        candidates = [e for e in candidates if UUID(e.get("article_id", "0" * 32)) in valid_ids]

        events_to_insert: list[NewsInteractionEvent] = []
        # (article_id, event_type, value_ms) for the post-commit Redis pass
        signal_events: list[tuple[UUID, str, int | None]] = []

        for e in candidates:
            article_id = UUID(e["article_id"])
            event_type = e["event_type"]
            occurred_at = _parse_occurred_at(e.get("occurred_at"), now)
            value_ms: int | None = None

            if event_type == "dwell" and e.get("value_ms") is not None:
                value_ms = min(int(e["value_ms"]), _DWELL_VALUE_CAP_MS)

            if event_type == "open_article":
                is_revisit = self._repo.upsert_view(profile_id, article_id)
                self._repo.adjust_article_stats(article_id, "view_count", 1)
                if is_revisit:
                    events_to_insert.append(
                        NewsInteractionEvent(
                            profile_id=profile_id,
                            article_id=article_id,
                            event_type="revisit",
                            occurred_at=occurred_at,
                            processed_at=now,
                        )
                    )
                    self._taste_from_article(profile_id, article_id, "revisit", rc=rc, session_action=ActionType.REVISIT)

            events_to_insert.append(
                NewsInteractionEvent(
                    profile_id=profile_id,
                    article_id=article_id,
                    event_type=event_type,
                    value_ms=value_ms,
                    occurred_at=occurred_at,
                )
            )
            signal_events.append((article_id, event_type, value_ms))

        self._repo.bulk_insert_events(events_to_insert)
        self._repo.commit()

        for article_id, event_type, value_ms in signal_events:
            action = _classify_action(event_type, value_ms)
            if action is None:
                continue
            enriched = self._repo.get_enriched_article(article_id)
            if enriched is None:
                continue
            write_news_signals(
                rc, profile_id,
                commodity_ids_for(self._repo, enriched.commodity_tags or []),
                enriched.location_city, enriched.location_state, action,
            )

        return {"accepted": len(events_to_insert), "dropped": len(raw_events) - len(candidates)}

    # -- Synchronous actions ----------------------------------------------------

    def toggle_like(self, profile_id: int, article_id: UUID, rc: redis.Redis | None = None) -> dict:
        if not self._repo.article_exists(article_id):
            raise ArticleNotFoundError(str(article_id))

        is_liked = self._repo.toggle_like(profile_id, article_id)
        delta = 1 if is_liked else -1
        self._repo.adjust_article_stats(article_id, "like_count", delta)

        if is_liked:
            self._taste_from_article(profile_id, article_id, "like", rc=rc, session_action=ActionType.LIKE)
        self._repo.commit()

        return {"is_liked": is_liked}

    def toggle_save(self, profile_id: int, article_id: UUID, rc: redis.Redis | None = None) -> dict:
        if not self._repo.article_exists(article_id):
            raise ArticleNotFoundError(str(article_id))

        is_saved = self._repo.toggle_save(profile_id, article_id)
        delta = 1 if is_saved else -1
        self._repo.adjust_article_stats(article_id, "save_count", delta)

        if is_saved:
            self._taste_from_article(profile_id, article_id, "save", rc=rc, session_action=ActionType.SAVE)
        self._repo.commit()

        return {"is_saved": is_saved}

    def record_share(
        self,
        profile_id: int,
        article_id: UUID,
        platform: str | None = None,
        rc: redis.Redis | None = None,
    ) -> None:
        if not self._repo.article_exists(article_id):
            raise ArticleNotFoundError(str(article_id))

        self._repo.record_share(profile_id, article_id, platform=platform)
        self._repo.adjust_article_stats(article_id, "share_count", 1)
        self._taste_from_article(profile_id, article_id, "share_tap", rc=rc, session_action=ActionType.SHARE)
        self._repo.commit()

    # -- Taste helpers ------------------------------------------------------------

    def _taste_from_article(
        self,
        profile_id: int,
        article_id: UUID,
        signal_type: str,
        *,
        rc: redis.Redis | None = None,
        session_action: ActionType | None = None,
    ) -> None:
        """
        Persistent taste (category dimension only, matching app_v1_backup) +
        Redis session-taste signal (commodity + city + state), from one
        enriched-article lookup.
        """
        enriched = self._repo.get_enriched_article(article_id)
        if enriched is None:
            return

        if enriched.primary_factor:
            pos, neg = _SIGNAL_WEIGHTS.get(signal_type, (0.0, 0.0))
            if pos or neg:
                self._repo.upsert_taste(
                    profile_id=profile_id,
                    dimension_type="category",
                    dimension_key=enriched.primary_factor,
                    positive_delta=pos,
                    negative_delta=neg,
                )

        if session_action is not None:
            write_news_signals(
                rc, profile_id,
                commodity_ids_for(self._repo, enriched.commodity_tags or []),
                enriched.location_city, enriched.location_state, session_action,
            )


# -- Module-level helpers --------------------------------------------------------

def _classify_signal(event_type: str, value_ms: int | None) -> str:
    if event_type == "dwell" and value_ms is not None:
        if value_ms < _DWELL_BOUNCE_MS:
            return "dwell_bounce"
        if value_ms < _DWELL_SHORT_MS:
            return "dwell_short"
        if value_ms < _DWELL_MEDIUM_MS:
            return "dwell_medium"
        return "dwell_long"
    return event_type


def _classify_action(event_type: str, value_ms: int | None) -> ActionType | None:
    key = _classify_signal(event_type, value_ms) if event_type == "dwell" else _EVENT_ALIAS.get(event_type, event_type)
    try:
        return ActionType(key)
    except ValueError:
        return None


def _parse_occurred_at(value: str | datetime | None, default: datetime) -> datetime:
    if value is None:
        return default
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except ValueError:
        return default
