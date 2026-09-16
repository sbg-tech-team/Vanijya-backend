"""Background jobs for the calling module — the runaway-cost guardrails.

Stream bills participants x wall-clock minutes, so a call that never ends bills
forever. These jobs are the layers that catch every way a call can fail to end.
Each one terminates the session ON STREAM as well as in our database: marking a
call ended locally does not stop the meter.

  run_ring_timeout_sweep()     30 s — unanswered ringing calls -> missed
  run_heartbeat_sweep()        30 s — every client gone (app killed) -> ended
  run_solo_participant_sweep() 60 s — one person left alone -> ended
  run_max_duration_sweep()     60 s — past the hard duration cap -> ended
  run_stale_call_reaper()       2 min — absolute backstop -> failed

Layering, weakest assumption last:

  Stream's own max_duration_seconds  (survives a total backend outage)
  Stream's inactivity timeout        (survives our outage, needs clients to drop)
  heartbeat sweep                    (needs our backend + a cooperating client)
  solo-participant sweep             (needs our backend)
  max-duration sweep                 (needs our backend)
  stale reaper                       (needs our backend; should never fire)

If the stale reaper is firing regularly, the layers above it are broken — it
logs at ERROR for that reason.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

import redis as redis_lib

from app.modules.calling.application import presence
from app.modules.calling.application.budget import record_usage
from app.modules.calling.domain.interfaces.push_sender import IPushSender
from app.modules.calling.domain.interfaces.repository import ICallingRepository
from app.modules.calling.domain.interfaces.video_provider import IVideoProvider
from app.modules.calling.domain.value_objects import (
    MAX_CALL_DURATION_SECONDS,
    RING_TIMEOUT_SECONDS,
    SOLO_PARTICIPANT_TIMEOUT_SECONDS,
    HEARTBEAT_TIMEOUT_SECONDS,
    PROVIDER_RETRY_WINDOW_SECONDS,
    STALE_CALL_TIMEOUT_SECONDS,
    CallStatus,
    CallType,
    EndReason,
    ParticipantState,
)

log = logging.getLogger(__name__)


def terminate_call(
    repo: ICallingRepository,
    provider: IVideoProvider,
    rc: redis_lib.Redis | None,
    call_id: UUID,
    status: str,
    end_reason: str,
    now: datetime,
    push: IPushSender | None = None,
) -> bool:
    """End one call everywhere: our database, Stream, and the budget counters.

    Ordering matters. Stream is told FIRST, because that is what stops the
    billing — if the database write then fails we have merely lost a history
    row, whereas the reverse would leave a session running that our records
    claim is over.
    """
    call = repo.get_call(call_id)
    if call is None or call.is_terminal():
        return False

    provider_ok = provider.end_call_remote(call.stream_call_type, call.stream_call_id)

    try:
        ended = repo.end_call(call_id, status, end_reason, now)
        if provider_ok:
            repo.mark_provider_ended(call_id, now)
        # A call the sweeper ends is still a call that happened. Without this a
        # missed call — the single most important card to show — would never
        # appear in the conversation.
        repo.write_call_card(
            context_type="group" if ended.call_type == CallType.GROUP.value else "dm",
            context_id=ended.context_id,
            sender_id=ended.initiator_id,
            call_id=ended.id,
            media=ended.media,
            status=ended.status,
            end_reason=ended.end_reason,
            duration_seconds=ended.duration_seconds,
            sent_at=now,
        )
        repo.commit()
    except Exception as exc:
        repo.rollback()
        log.error("terminate_call: db write failed for %s: %s", call_id, exc)
        return False

    # Bill the abandoned time against budget too, or reapers would be a blind
    # spot in exactly the scenario that costs the most.
    if ended.duration_seconds > 0:
        record_usage(
            rc,
            [p.user_id for p in ended.participants],
            ended.duration_seconds,
        )

    presence.clear(rc, call_id, [p.user_id for p in ended.participants])
    _notify_ended(repo, ended, now, push)
    return True


def _notify_ended(
    repo: ICallingRepository, ended, now: datetime, push: IPushSender | None
) -> None:
    """Tell everyone the call is over — socket first, push as the fallback.

    Jobs run in APScheduler worker threads with no event loop and no
    BackgroundTasks, so emits are handed back to the Socket.IO loop explicitly.
    Skipping this would leave a caller watching a ringing screen for a call the
    backend has already marked missed, and — worse — leave a backgrounded client
    holding its media session open, still billing.
    """
    payload = {
        "call_id": str(ended.id),
        "ended_by": None,
        "ended_at": ended.ended_at.isoformat() if ended.ended_at else now.isoformat(),
        "duration_seconds": ended.duration_seconds,
        "end_reason": ended.end_reason,
    }
    user_ids = [p.user_id for p in ended.participants]

    try:
        from app.core.realtime import (
            emit_threadsafe, emit_to_group, emit_to_user,
        )
        if ended.call_type == CallType.GROUP.value:
            emit_threadsafe(emit_to_group(ended.context_id, "call_ended", payload))
        else:
            for uid in user_ids:
                emit_threadsafe(emit_to_user(uid, "call_ended", payload))
    except Exception as exc:
        log.warning("call_ended emit failed for %s: %s", ended.id, exc)

    try:
        targets = repo.push_targets(user_ids)
        if targets and push is not None:
            push.send_data(targets, {
                "type": "call_ended",
                "call_id": str(ended.id),
                "end_reason": ended.end_reason or "",
                "duration_seconds": str(ended.duration_seconds),
            })
    except Exception as exc:
        log.warning("call_ended push failed for %s: %s", ended.id, exc)


def _sweep(
    repo: ICallingRepository,
    provider: IVideoProvider,
    push: IPushSender | None,
    rc: redis_lib.Redis | None,
    pick,
    status: str,
    end_reason: str,
    label: str,
    level: int = logging.INFO,
) -> dict:
    now = datetime.now(timezone.utc)

    swept = 0
    for call_id in pick(repo, now):
        try:
            if terminate_call(repo, provider, rc, call_id, status, end_reason, now, push):
                swept += 1
        except Exception as exc:
            repo.rollback()
            log.error("%s failed for call %s: %s", label, call_id, exc)

    if swept:
        log.log(level, "%s: %d call(s) ended", label, swept)
    return {label: swept}


def _redis():
    """Budget counters are best-effort; a Redis outage must not stop a sweep."""
    try:
        from app.core.redis_client import get_redis
        return get_redis()
    except Exception:
        return None


# ── Layer 1: nobody answered ──────────────────────────────────────────────────

def run_ring_timeout_sweep(
    repo: ICallingRepository,
    provider: IVideoProvider,
    push: IPushSender | None = None,
) -> dict:
    return _sweep(
        repo, provider, push, _redis(),
        lambda repo, now: repo.expired_ringing_call_ids(
            now - timedelta(seconds=RING_TIMEOUT_SECONDS)
        ),
        CallStatus.MISSED.value, EndReason.MISSED.value,
        "calls.ring_timeout",
    )


def _presence_filtered(repo, rc, call_ids: list, want_present: int) -> list:
    """Narrow a DB-derived candidate list by live Redis presence.

    The SQL sweeps use the `last_heartbeat_at` column, which is now only written
    when Redis is unavailable — so on its own it would look stale for every
    healthy call and sweep the platform. Redis is therefore the authority when
    it answers, and when it does not the caller skips the sweep completely.
    """
    out = []
    for cid in call_ids:
        call = repo.get_call(cid)
        if call is None:
            continue
        candidates = [
            p.user_id for p in call.participants
            if p.state == ParticipantState.JOINED.value
        ]
        present = presence.present_user_ids(rc, cid, candidates)
        if present is None:
            continue                       # no data — never guess
        if len(present) == want_present:
            out.append(cid)
    return out


# ── Layer 2: one participant left talking to nobody ───────────────────────────

def run_solo_participant_sweep(
    repo: ICallingRepository,
    provider: IVideoProvider,
    push: IPushSender | None = None,
) -> dict:
    """The common real-world leak: B's phone dies mid-call, A's phone sits in a
    pocket. Nothing is wrong from A's client's point of view, so it never sends
    `end`, and the call bills until the hard cap. Ending it costs the user
    nothing — there was nobody on the other side."""
    return _sweep(
        repo, provider, push, _redis(),
        lambda repo, now: _presence_filtered(
            repo, _redis(),
            repo.active_call_ids_started_before(
                now - timedelta(seconds=SOLO_PARTICIPANT_TIMEOUT_SECONDS)
            ),
            want_present=1,
        ),
        CallStatus.ENDED.value, EndReason.TIMEOUT.value,
        "calls.solo_timeout",
    )


# ── Layer 3: every client is gone ─────────────────────────────────────────────

def run_heartbeat_sweep(
    repo: ICallingRepository,
    provider: IVideoProvider,
    push: IPushSender | None = None,
) -> dict:
    """The strongest liveness guardrail, and the direct answer to "what if the
    user just closes the app mid-call".

    Clients ping while they are in a call. When the pings stop, every client is
    gone — force-quit, crashed, or out of battery — and nothing else will ever
    tell us the call is over. Ninety seconds later it is torn down, instead of
    billing until the two-hour cap and leaving both users marked busy until
    then."""
    return _sweep(
        repo, provider, push, _redis(),
        lambda repo, now: _presence_filtered(
            repo, _redis(),
            repo.active_call_ids_started_before(
                now - timedelta(seconds=HEARTBEAT_TIMEOUT_SECONDS)
            ),
            want_present=0,
        ),
        CallStatus.ENDED.value, EndReason.TIMEOUT.value,
        "calls.heartbeat_timeout",
    )


# ── Layer 4: hard duration cap ────────────────────────────────────────────────

def run_max_duration_sweep(
    repo: ICallingRepository,
    provider: IVideoProvider,
    push: IPushSender | None = None,
) -> dict:
    """Backs up the cap Stream enforces itself. If this fires, the Stream-side
    cap did not — worth knowing, so it logs at WARNING."""
    return _sweep(
        repo, provider, push, _redis(),
        lambda repo, now: repo.overlong_call_ids(
            now - timedelta(seconds=MAX_CALL_DURATION_SECONDS)
        ),
        CallStatus.ENDED.value, EndReason.TIMEOUT.value,
        "calls.max_duration",
        level=logging.WARNING,
    )


# ── Layer 5: the provider was never told ──────────────────────────────────────

def run_provider_termination_retry(
    repo: ICallingRepository,
    provider: IVideoProvider,
    push: IPushSender | None = None,
) -> dict:
    """Retry mark_ended for calls we finished but could not terminate remotely.

    Every other sweep skips terminal calls, so without this a single failed
    mark_ended — a Stream blip, a network hiccup — leaves a media session
    running forever with nothing left to notice. It is the only failure that
    keeps costing money after the call is over in every other respect.
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(seconds=PROVIDER_RETRY_WINDOW_SECONDS)

    fixed = 0
    for call_id in repo.unterminated_provider_call_ids(since):
        call = repo.get_call(call_id)
        if call is None:
            continue
        try:
            if provider.end_call_remote(call.stream_call_type, call.stream_call_id):
                repo.mark_provider_ended(call_id, now)
                repo.commit()
                fixed += 1
        except Exception as exc:
            repo.rollback()
            log.error("provider termination retry failed for %s: %s", call_id, exc)

    if fixed:
        log.warning("calls.provider_retry: %d session(s) terminated late", fixed)
    return {"calls.provider_retry": fixed}


# ── Layer 6: absolute backstop ────────────────────────────────────────────────

def run_stale_call_reaper(
    repo: ICallingRepository,
    provider: IVideoProvider,
    push: IPushSender | None = None,
) -> dict:
    """Should never fire: the max-duration sweep catches these two hours
    earlier. Logged at ERROR because a hit means the layers above are broken."""
    return _sweep(
        repo, provider, push, _redis(),
        lambda repo, now: repo.stale_active_call_ids(
            now - timedelta(seconds=STALE_CALL_TIMEOUT_SECONDS)
        ),
        CallStatus.FAILED.value, EndReason.FAILED.value,
        "calls.stale_reaper",
        level=logging.ERROR,
    )
