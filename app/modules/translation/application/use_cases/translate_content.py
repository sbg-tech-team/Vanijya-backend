from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from app.modules.translation.domain.content import (
    STATUS_FAILED,
    STATUS_IN_PROGRESS,
    STATUS_NOT_FOUND,
    STATUS_READY,
    ContentRef,
    ContentSource,
    FieldValue,
    ItemResult,
    TranslationShapeError,
    field_hash,
    split_fresh,
    validate_shape,
)
from app.modules.translation.domain.content_prompt import assemble_content_prompt
from app.modules.translation.domain.exceptions import TranslationEngineUnavailableError
from app.modules.translation.domain.interfaces.content_engine import IContentTranslationEngine
from app.modules.translation.domain.interfaces.content_repository import IContentTranslationRepository
from app.modules.translation.domain.interfaces.translation_lock import ITranslationLock
from app.modules.translation.domain.value_objects import (
    CONTENT_ITEMS_PER_ENGINE_CALL,
    CONTENT_LOCK_TTL_SECONDS,
    CONTENT_WAIT_POLL_SECONDS,
    CONTENT_WAIT_SECONDS,
)

log = logging.getLogger(__name__)

# One pending item: the source, and just the fields it still needs.
_Pending = tuple[ContentSource, dict[str, FieldValue]]


class TranslateContentUseCase:
    """On-command translation of posts, comments and news — database first.

      1. Load every requested item with its stored translation for this
         language (one query per content type). Fields already translated
         from the current source are returned as-is: no engine call.
      2. For the rest, take a per-(item, language) lock. The holder calls the
         engine — several items per call — validates the output and stores it
         on the item. Whoever loses the lock waits briefly and re-reads the
         database instead of paying for the same translation twice.
      3. Nothing is stored unless its shape matches what was sent, so one bad
         engine response is never served to later readers.

    `before_engine_call` runs once, only if the engine is actually needed —
    it is where the caller rate-limits, so cache hits are never counted.

    Raises TranslationEngineUnavailableError only when something needs
    translating and no engine key is configured; a request served entirely
    from the database works without one.
    """

    def __init__(
        self,
        repository: IContentTranslationRepository,
        engine: IContentTranslationEngine,
        lock: ITranslationLock,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.repository = repository
        self.engine = engine
        self.lock = lock
        self._sleep = sleep
        self._clock = clock

    def execute(
        self,
        viewer_profile_id: int,
        refs: list[ContentRef],
        target_lang: str,
        before_engine_call: Optional[Callable[[], None]] = None,
    ) -> list[ItemResult]:
        # A repeated item is one item — by key, not by the whole ref, so the
        # same post asked for twice with different `fields` does not wait on
        # its own lock. The first occurrence wins.
        first: dict[str, ContentRef] = {}
        for ref in refs:
            first.setdefault(ref.key, ref)
        refs = list(first.values())
        loaded = self.repository.load(refs, target_lang, viewer_profile_id)

        results: dict[str, ItemResult] = {}
        pending: list[_Pending] = []
        for ref in refs:
            if ref.key not in loaded:
                results[ref.key] = ItemResult(ref=ref, status=STATUS_NOT_FOUND)
                continue
            source, stored = loaded[ref.key]
            ready, todo = split_fresh(source, stored)
            if not todo:
                results[ref.key] = ItemResult(ref=ref, status=STATUS_READY, fields=ready, cached=True)
            else:
                pending.append((source, todo))

        if pending:
            self._translate_pending(pending, target_lang, viewer_profile_id, before_engine_call, results)

        return [results[ref.key] for ref in refs]

    # ── engine path ──────────────────────────────────────────────────────────

    def _translate_pending(
        self,
        pending: list[_Pending],
        target_lang: str,
        viewer_profile_id: int,
        before_engine_call: Optional[Callable[[], None]],
        results: dict[str, ItemResult],
    ) -> None:
        if not self.engine.is_configured:
            # An environment without a key: say so (503), rather than report
            # every item "failed" as if the text were the problem.
            raise TranslationEngineUnavailableError("Translation engine is not configured")

        mine: list[_Pending] = []
        waiting: list[ContentRef] = []
        for source, todo in pending:
            if self.lock.acquire(self._lock_key(source.ref, target_lang), CONTENT_LOCK_TTL_SECONDS):
                mine.append((source, todo))
            else:
                waiting.append(source.ref)

        try:
            if mine:
                if before_engine_call is not None:
                    before_engine_call()
                for i in range(0, len(mine), CONTENT_ITEMS_PER_ENGINE_CALL):
                    self._translate_batch(mine[i:i + CONTENT_ITEMS_PER_ENGINE_CALL], target_lang)
        finally:
            for source, _ in mine:
                self.lock.release(self._lock_key(source.ref, target_lang))

        # Re-read everything that was pending: what this call stored, and what
        # another request stored while we waited on its lock.
        self._collect(
            [s.ref for s, _ in mine], waiting, target_lang, viewer_profile_id, results
        )

    def _translate_batch(self, batch: list[_Pending], target_lang: str) -> None:
        prompt = assemble_content_prompt(items=batch, target_lang=target_lang)
        try:
            response = self.engine.translate_fields(prompt)
        except Exception as exc:
            # Engine outage or timeout. Items stay untranslated and are
            # reported failed; the next tap tries again.
            log.warning("content translation call failed (%d items, %s): %s",
                        len(batch), target_lang, exc)
            return

        if not isinstance(response, dict):
            log.warning("content translation returned %s, not an object", type(response).__name__)
            return

        for source, todo in batch:
            try:
                translated = validate_shape(todo, response.get(source.ref.key))
            except TranslationShapeError as exc:
                log.warning("content translation for %s rejected: %s", source.ref.key, exc)
                continue
            self.repository.save_fields(
                source.ref,
                target_lang,
                {name: (field_hash(todo[name]), text) for name, text in translated.items()},
            )

    def _collect(
        self,
        translated: list[ContentRef],
        waiting: list[ContentRef],
        target_lang: str,
        viewer_profile_id: int,
        results: dict[str, ItemResult],
    ) -> None:
        outstanding = {r.key: r for r in translated + waiting}
        deadline = self._clock() + (CONTENT_WAIT_SECONDS if waiting else 0)

        while True:
            loaded = self.repository.load(list(outstanding.values()), target_lang, viewer_profile_id)
            for key, ref in list(outstanding.items()):
                if key not in loaded:
                    results[key] = ItemResult(ref=ref, status=STATUS_NOT_FOUND)
                    del outstanding[key]
                    continue
                ready, todo = split_fresh(*loaded[key])
                if not todo:
                    # Stored by someone else while we waited -> it was cached for us.
                    results[key] = ItemResult(ref=ref, status=STATUS_READY, fields=ready,
                                              cached=ref not in translated)
                    del outstanding[key]
                elif ref in translated:
                    # We held the lock and still have no translation: the engine
                    # failed or its output was rejected. No point waiting.
                    results[key] = ItemResult(ref=ref, status=STATUS_FAILED, fields=ready or None)
                    del outstanding[key]

            if not outstanding or self._clock() >= deadline:
                break
            self._sleep(CONTENT_WAIT_POLL_SECONDS)

        for key, ref in outstanding.items():
            results[key] = ItemResult(ref=ref, status=STATUS_IN_PROGRESS)

    @staticmethod
    def _lock_key(ref: ContentRef, target_lang: str) -> str:
        return f"content_translate:{ref.key}:{target_lang}"
