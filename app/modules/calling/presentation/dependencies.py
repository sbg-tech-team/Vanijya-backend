from uuid import UUID

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database.session import SessionLocal
from app.dependencies import get_db
from app.modules.calling.application import jobs as calling_jobs
from app.modules.calling.application.use_cases.drop_on_block import drop_calls_between
from app.modules.calling.data.adapters.fcm import FcmPushSender
from app.modules.calling.data.adapters.stream_video import StreamVideoProvider
from app.modules.calling.data.repository import CallingRepository
from app.modules.calling.domain.interfaces.push_sender import IPushSender
from app.modules.calling.domain.interfaces.repository import ICallingRepository
from app.modules.calling.domain.interfaces.video_provider import IVideoProvider

# Both adapters are stateless and cheap to construct, but there's no reason to
# rebuild them per request — the provider reads settings once at init.
_video_provider = StreamVideoProvider()
_push_sender = FcmPushSender()


def get_calling_repo(db: Session = Depends(get_db)) -> ICallingRepository:
    return CallingRepository(db)


def get_video_provider() -> IVideoProvider:
    return _video_provider


def get_push_sender() -> IPushSender:
    return _push_sender


# ── Background-task composition ──────────────────────────────────────────────
# A BackgroundTask runs after the request (and its session) is gone, so it has
# to own a session. Composing it here keeps the use case free of both the
# session and the concrete adapters.

def drop_calls_between_task(user_a: UUID, user_b: UUID) -> int:
    """Background entry point for drop-on-block. Opens its own session."""
    db = SessionLocal()
    try:
        return drop_calls_between(
            CallingRepository(db), _video_provider, user_a, user_b,
            rc=_optional_redis(), push=_push_sender,
        )
    finally:
        db.close()


def push_task(user_ids: list[UUID], data: dict) -> int:
    """Background entry point for one push fan-out.

    Owns its session because the request's is already closed by the time a
    BackgroundTask runs. Tokens FCM reports as dead are deleted here — without
    that, an uninstalled app's token is retried on every single call forever.
    """
    db = SessionLocal()
    try:
        repo = CallingRepository(db)
        targets = repo.push_targets(user_ids)
        if not targets:
            return 0
        dead: list[str] = []
        delivered = _push_sender.send_data(targets, data, on_dead=dead.append)
        if dead:
            repo.delete_devices(dead)
            repo.commit()
        return delivered
    finally:
        db.close()


def _optional_redis():
    """Presence/budget counters are best-effort; a Redis outage must not block."""
    try:
        from app.core.redis_client import get_redis
        return get_redis()
    except Exception:
        return None


# ── Scheduled-job composition ────────────────────────────────────────────────
# Every calling sweep needs the same three collaborators and its own session.

def _run_call_job(job) -> dict:
    db = SessionLocal()
    try:
        return job(CallingRepository(db), _video_provider, _push_sender)
    finally:
        db.close()


def run_ring_timeout_job() -> dict:
    return _run_call_job(calling_jobs.run_ring_timeout_sweep)


def run_heartbeat_job() -> dict:
    return _run_call_job(calling_jobs.run_heartbeat_sweep)


def run_solo_participant_job() -> dict:
    return _run_call_job(calling_jobs.run_solo_participant_sweep)


def run_max_duration_job() -> dict:
    return _run_call_job(calling_jobs.run_max_duration_sweep)


def run_provider_retry_job() -> dict:
    return _run_call_job(calling_jobs.run_provider_termination_retry)


def run_stale_reaper_job() -> dict:
    return _run_call_job(calling_jobs.run_stale_call_reaper)
