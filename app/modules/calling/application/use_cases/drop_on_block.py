"""End any live call between two users the moment one blocks the other.

Blocking only gating NEW calls would make the feature look broken: the person
you just blocked is still talking to you. This runs as a background task off the
block endpoint, so a slow provider call never delays the block itself.

Pure application logic: the session and the concrete adapters are composed by
`calling.presentation.dependencies.drop_calls_between_task`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

import redis as redis_lib

from app.modules.calling.application.jobs import terminate_call
from app.modules.calling.domain.interfaces.push_sender import IPushSender
from app.modules.calling.domain.interfaces.repository import ICallingRepository
from app.modules.calling.domain.interfaces.video_provider import IVideoProvider
from app.modules.calling.domain.value_objects import CallStatus, EndReason

log = logging.getLogger(__name__)


def drop_calls_between(
    repo: ICallingRepository,
    provider: IVideoProvider,
    user_a: UUID,
    user_b: UUID,
    rc: redis_lib.Redis | None = None,
    push: IPushSender | None = None,
) -> int:
    """Terminate every ringing/active call the pair share. Returns how many."""
    now = datetime.now(timezone.utc)

    dropped = 0
    for call_id in repo.live_call_ids_between(user_a, user_b):
        try:
            if terminate_call(
                repo, provider, rc, call_id,
                CallStatus.ENDED.value, EndReason.HUNG_UP.value, now, push,
            ):
                dropped += 1
        except Exception as exc:
            repo.rollback()
            log.error("drop-on-block failed for call %s: %s", call_id, exc)

    if dropped:
        log.info("drop-on-block: ended %d call(s) between %s and %s",
                 dropped, user_a, user_b)
    return dropped
