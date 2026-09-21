"""Scheduled recovery for continuous translation.

The live path translates in a FastAPI BackgroundTask, which is in-process and
unacknowledged: a deploy, a crash or an OOM between the message landing and
the translation finishing loses it with nothing to retry from. Before
translations were persisted there was no way to even detect that; now a
missing message_translations row for a continuous reader IS the detection.

This sweep re-runs those. It is a safety net, not the main path — a healthy
process translates on arrival and this finds nothing.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.modules.translation.domain.interfaces.repository import ITranslationRepository

log = logging.getLogger(__name__)

# How far back to look. Long enough to cover a deploy or a crash-restart,
# short enough that the query stays cheap and we never resurrect translations
# for a conversation nobody is reading any more.
LOOKBACK_MINUTES = 60
# Ceiling per run. A backlog drains over several runs instead of one sweep
# firing hundreds of paid Gemini calls in a burst.
MAX_PER_RUN = 50


def run_translation_retry(
    repo: ITranslationRepository,
    handle_incoming,
    now: datetime | None = None,
) -> dict:
    """`handle_incoming` is HandleIncomingMessageUseCase.execute — it re-checks
    the reader's preference itself, so a reader who switched continuous off in
    the meantime is skipped rather than translated late."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(minutes=LOOKBACK_MINUTES)

    pending = repo.untranslated_for_continuous_readers(since, MAX_PER_RUN)
    if not pending:
        return {"pending": 0, "translated": 0, "failed": 0}

    translated = failed = 0
    for receiver_id, message_id in pending:
        try:
            if handle_incoming(receiver_id=receiver_id, message_id=message_id):
                translated += 1
        except Exception as exc:
            # One bad message must not stop the rest of the backlog. Logged,
            # not swallowed: a failure here is a translation the reader never
            # gets, and the next run will try it again anyway.
            failed += 1
            log.warning("translation retry failed for message %s: %s", message_id, exc)

    log.info("translation retry: %d pending, %d translated, %d failed",
             len(pending), translated, failed)
    return {"pending": len(pending), "translated": translated, "failed": failed}
