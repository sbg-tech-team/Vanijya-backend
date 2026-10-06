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
from typing import Protocol
from uuid import UUID

import redis

from app.modules.news.domain.entities import NewsInteractionEvent
from app.modules.news.domain.exceptions import ArticleNotFoundError
from app.modules.news.domain.interfaces.repository import INewsRepository
from app.modules.news.domain.value_objects import CLIENT_EVENT_TYPES
from app.recommendation.amplify import commodity_ids_for, write_news_signals
from app.recommendation.session_taste import ActionType

log = logging.getLogger(__name__)


class TaskQueue(Protocol):
    """Shaped like fastapi.BackgroundTasks' add_task — the application layer
    stays framework-free, so it depends on this shape, not on FastAPI; the
    presentation layer passes the real BackgroundTasks object in. Same
    convention as the posts module's interact_post.TaskQueue."""
    def add_task(self, func, *args, **kwargs) -> None: ...

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

# Signals strong enough to invalidate the cached "default" feed ranking so the
# next request re-scores instead of serving a stale page for up to 2h.
_CACHE_INVALIDATING_EVENTS = frozenset({"like", "save", "revisit"})


class RecordInteractionUseCase:

    def __init__(self, repo: INewsRepository) -> None:
        self._repo = repo

    # -- Bulk event batch (client-submitted) -----------------------------------

    def process_event_batch(
        self,
        profile_id: int,
        raw_events: list[dict],
        background_tasks: TaskQueue,
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

        # Aggregate open_article events per article up front — a batch of up
        # to BATCH_MAX_EVENTS used to mean that many separate upsert_view() +
        # adjust_article_stats() round trips, one per event. Revisit status is
        # now determined once per distinct article from state BEFORE this
        # batch (not progressively within it, unlike the old per-event
        # sequential check) — the same article opened twice in one batch is
        # the rare edge case this trades away for a small constant number of
        # round trips instead of one pair per open_article event.
        open_article_counts: dict[UUID, int] = {}
        open_article_last_at: dict[UUID, datetime] = {}
        for e in candidates:
            if e["event_type"] != "open_article":
                continue
            article_id = UUID(e["article_id"])
            occurred_at = _parse_occurred_at(e.get("occurred_at"), now)
            open_article_counts[article_id] = open_article_counts.get(article_id, 0) + 1
            if article_id not in open_article_last_at or occurred_at > open_article_last_at[article_id]:
                open_article_last_at[article_id] = occurred_at

        revisit_ids = self._repo.get_existing_view_article_ids(profile_id, list(open_article_counts))

        events_to_insert: list[NewsInteractionEvent] = []
        # (article_id, event_type, value_ms) for the deferred signal pass
        signal_events: list[tuple[UUID, str, int | None]] = []
        revisit_taste_ids: set[UUID] = set()
        invalidate_cache = False

        for e in candidates:
            article_id = UUID(e["article_id"])
            event_type = e["event_type"]
            occurred_at = _parse_occurred_at(e.get("occurred_at"), now)
            value_ms: int | None = None

            if event_type == "dwell" and e.get("value_ms") is not None:
                value_ms = min(int(e["value_ms"]), _DWELL_VALUE_CAP_MS)

            if event_type == "open_article" and article_id in revisit_ids:
                events_to_insert.append(
                    NewsInteractionEvent(
                        profile_id=profile_id,
                        article_id=article_id,
                        event_type="revisit",
                        occurred_at=occurred_at,
                        processed_at=now,
                    )
                )
                revisit_taste_ids.add(article_id)
                invalidate_cache = True

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

        if open_article_counts:
            self._repo.upsert_views_batch(profile_id, open_article_counts, open_article_last_at)
            self._repo.adjust_article_stats_batch("view_count", open_article_counts)

        self._repo.bulk_insert_events(events_to_insert)
        if invalidate_cache:
            self._repo.invalidate_feed_ranking_cache(profile_id)  # commits
        self._repo.commit()

        # Revisit taste writes + per-event Redis session signals are
        # best-effort analytics that don't affect this response — deferred
        # the same way toggle_like/toggle_save/record_share defer theirs,
        # using one batched enriched-article fetch instead of one per event.
        all_ids = {article_id for article_id, _, _ in signal_events} | revisit_taste_ids
        enriched_by_id = self._repo.get_enriched_articles(list(all_ids)) if all_ids else {}

        def _run():
            try:
                for article_id in revisit_taste_ids:
                    enriched = enriched_by_id.get(article_id)
                    if enriched is not None:
                        self._apply_taste_signal(
                            profile_id, enriched, "revisit", rc=rc, session_action=ActionType.REVISIT
                        )
                for article_id, event_type, value_ms in signal_events:
                    action = _classify_action(event_type, value_ms)
                    if action is None:
                        continue
                    enriched = enriched_by_id.get(article_id)
                    if enriched is None:
                        continue
                    write_news_signals(
                        rc, profile_id,
                        commodity_ids_for(self._repo, enriched.commodity_tags or []),
                        enriched.location_city, enriched.location_state, action,
                    )
                self._repo.commit()
            except Exception:
                log.exception("deferred batch taste/signal processing failed for profile %s", profile_id)
        background_tasks.add_task(_run)

        return {"accepted": len(events_to_insert), "dropped": len(raw_events) - len(candidates)}

    # -- Synchronous actions ----------------------------------------------------

    def toggle_like(
        self, profile_id: int, article_id: UUID, background_tasks: TaskQueue, rc: redis.Redis | None = None
    ) -> dict:
        if not self._repo.article_exists(article_id):
            raise ArticleNotFoundError(str(article_id))

        is_liked = self._repo.toggle_like(profile_id, article_id)
        delta = 1 if is_liked else -1
        self._repo.adjust_article_stats(article_id, "like_count", delta)
        self._repo.commit()

        if is_liked:
            self._defer_taste_and_cache_invalidation(
                background_tasks, profile_id, article_id, "like", ActionType.LIKE, rc, invalidate_cache=True,
            )

        return {"is_liked": is_liked}

    def toggle_save(
        self, profile_id: int, article_id: UUID, background_tasks: TaskQueue, rc: redis.Redis | None = None
    ) -> dict:
        if not self._repo.article_exists(article_id):
            raise ArticleNotFoundError(str(article_id))

        is_saved = self._repo.toggle_save(profile_id, article_id)
        delta = 1 if is_saved else -1
        self._repo.adjust_article_stats(article_id, "save_count", delta)
        self._repo.commit()

        if is_saved:
            self._defer_taste_and_cache_invalidation(
                background_tasks, profile_id, article_id, "save", ActionType.SAVE, rc, invalidate_cache=True,
            )

        return {"is_saved": is_saved}

    def record_share(
        self,
        profile_id: int,
        article_id: UUID,
        background_tasks: TaskQueue,
        platform: str | None = None,
        rc: redis.Redis | None = None,
    ) -> None:
        if not self._repo.article_exists(article_id):
            raise ArticleNotFoundError(str(article_id))

        self._repo.record_share(profile_id, article_id, platform=platform)
        self._repo.adjust_article_stats(article_id, "share_count", 1)
        self._repo.commit()

        self._defer_taste_and_cache_invalidation(
            background_tasks, profile_id, article_id, "share_tap", ActionType.SHARE, rc, invalidate_cache=False,
        )

    def _defer_taste_and_cache_invalidation(
        self,
        background_tasks: TaskQueue,
        profile_id: int,
        article_id: UUID,
        signal_type: str,
        session_action: ActionType,
        rc: redis.Redis | None,
        invalidate_cache: bool,
    ) -> None:
        """Taste write + session signal (+ feed-ranking cache invalidation for
        like/save) is best-effort analytics, not something the caller's
        response should wait on — runs after the response goes out instead of
        blocking it, same convention as the posts module's deferred taste
        writes (interact_post._defer_record_interaction). The core state
        change (the like/save/share row + its counter) already committed
        before this is scheduled, so this only needs its own commit."""
        def _run():
            try:
                self._taste_from_article(profile_id, article_id, signal_type, rc=rc, session_action=session_action)
                if invalidate_cache:
                    self._repo.invalidate_feed_ranking_cache(profile_id)  # commits
                self._repo.commit()
            except Exception:
                log.exception(
                    "deferred taste/cache update failed for %s on article %s by profile %s",
                    signal_type, article_id, profile_id,
                )
        background_tasks.add_task(_run)

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
        """Single-article version of _apply_taste_signal — fetches the
        enriched article itself. Batch callers (process_event_batch) already
        have it prefetched and call _apply_taste_signal directly instead."""
        enriched = self._repo.get_enriched_article(article_id)
        if enriched is None:
            return
        self._apply_taste_signal(profile_id, enriched, signal_type, rc=rc, session_action=session_action)

    def _apply_taste_signal(
        self,
        profile_id: int,
        enriched,
        signal_type: str,
        *,
        rc: redis.Redis | None = None,
        session_action: ActionType | None = None,
    ) -> None:
        """
        Persistent taste (category dimension only, matching app_v1_backup) +
        Redis session-taste signal (commodity + city + state), from an
        already-fetched enriched article.
        """
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
