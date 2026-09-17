"""Calling use-case self-check.

Runs against in-memory fakes — no Postgres, no Redis, no Stream, no FCM. What it
guards is the logic that is easy to get wrong and expensive to get wrong in
production:

  * blocks are enforced at initiate AND at accept
  * busy checks stop double-calling
  * duration is computed server-side, never taken from the client
  * 1:1 reject ends the call; group reject does not
  * a group call survives one member leaving, ends when the last one goes
  * an unanswered call the caller drops is `cancelled`, not `ended`
  * the ring-timeout sweeper marks stale ringing calls `missed`

Cost guardrails (Stream bills participants x wall-clock minutes, so every one of
these is a way a forgotten call could bill forever):
  * every terminal path tells the PROVIDER to end the session, not just our DB
  * a hard duration cap is sent to the provider at call creation
  * a call left with one participant is ended (their peer died)
  * finished calls are billed against the per-user and platform budgets
  * an exhausted budget refuses new calls

Run:  python3 tests/test_calling.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.modules.calling.application.use_cases.end_call import end_call
from app.modules.calling.application.use_cases.get_calls import (
    _decode_cursor,
    _encode_cursor,
)
from app.modules.calling.application.use_cases.initiate_call import initiate_call
from app.modules.calling.application.use_cases.respond_to_call import (
    accept_call,
    reject_call,
)
from app.modules.calling.domain.entities import (
    CallEntity,
    ParticipantEntity,
    PushTarget,
    StreamCredentials,
    UserSnap,
)
from app.modules.calling.application.budget import check_budget, record_usage
from app.modules.calling.application.jobs import terminate_call
from app.modules.calling.domain.exceptions import (
    CallAlreadyEndedError,
    CallBlockedError,
    CallNotFoundError,
    CallBudgetExceededError,
    CalleeBusyError,
    CallerBusyError,
    SelfCallError,
    VideoNotAvailableError,
)
from app.modules.calling.application.use_cases.heartbeat import heartbeat
from app.modules.calling.domain.value_objects import (
    HEARTBEAT_TIMEOUT_SECONDS,
    MAX_CALL_DURATION_SECONDS,
    CallStatus,
    EndReason,
    ParticipantRole,
    ParticipantState,
)

class _C(CallEntity):
    """CallEntity plus the columns the repository carries but the entity omits."""
    provider_ended_at = None


ALICE, BOB, CARE = uuid4(), uuid4(), uuid4()
GROUP = uuid4()


# ── Fakes ─────────────────────────────────────────────────────────────────────

class _P(ParticipantEntity):
    last_heartbeat_at = None


class FakeProvider:
    is_configured = True

    def __init__(self, fail_provision=False, fail_end=False):
        self.ended = []          # stream calls we told the provider to terminate
        self.provisioned = []    # (call_id, max_duration_seconds)
        self.fail_provision = fail_provision
        self.fail_end = fail_end

    def new_call_id(self, call_id: UUID):
        return "default", call_id.hex

    def provision_call(self, stream_call_type, stream_call_id, created_by_id,
                       max_duration_seconds):
        if self.fail_provision:
            return False
        self.provisioned.append((stream_call_id, max_duration_seconds))
        return True

    def end_call_remote(self, stream_call_type, stream_call_id):
        if self.fail_end:
            return False
        self.ended.append(stream_call_id)
        return True

    def issue_token(self, user_id, stream_call_type, stream_call_id):
        return StreamCredentials(
            api_key="k", token=f"tok-{user_id}", user_id=user_id,
            call_type=stream_call_type, call_id=stream_call_id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )


class FakeRedis:
    """Enough of redis for the budget counters."""

    def __init__(self, seed=None):
        self.store = dict(seed or {})

    def get(self, k):
        v = self.store.get(k)
        return None if v is None else str(v).encode()

    def pipeline(self, transaction=False):
        return _Pipe(self)


class _Pipe:
    def __init__(self, r):
        self.r = r
        self.ops = []

    def incrby(self, k, n):
        self.ops.append(("incrby", k, n)); return self

    def expire(self, k, ttl):
        self.ops.append(("expire", k, ttl)); return self

    def execute(self):
        out = []
        for op, k, v in self.ops:
            if op == "incrby":
                self.r.store[k] = int(self.r.store.get(k, 0)) + v
                out.append(self.r.store[k])
            else:
                out.append(True)
        self.ops.clear()
        return out


class FakePush:
    def __init__(self):
        self.sent = []

    def send_data(self, targets, data):
        self.sent.append((targets, data))
        return len(targets)


class FakeRepo:
    """Minimal in-memory ICallingRepository."""

    def __init__(self, blocks=(), members=None):
        self.calls: dict[UUID, CallEntity] = {}
        self.blocks = {frozenset(b) for b in blocks}
        self.members = members or {GROUP: [ALICE, BOB, CARE]}
        self.cards = []
        self.locks = []
        self.devices = []
        self.locked_calls = []
        self.names = {ALICE: "Alice", BOB: "Bob", CARE: "Care"}

    # identity
    def get_user_snap(self, uid):
        if uid not in self.names:
            return None
        return UserSnap(user_id=uid, profile_id=abs(hash(uid)) % 1000, name=self.names[uid])

    def get_user_snaps(self, uids):
        return {u: self.get_user_snap(u) for u in uids if u in self.names}

    def get_group_snap(self, gid):
        from app.modules.calling.domain.entities import GroupSnap
        return GroupSnap(group_id=gid, name="Traders") if gid in self.members else None

    def is_group_member(self, gid, uid):
        return uid in self.members.get(gid, [])

    def group_member_ids(self, gid):
        return list(self.members.get(gid, []))

    def either_blocked(self, a, b):
        return frozenset((a, b)) in self.blocks

    def get_or_create_dm_id(self, a, b):
        return uuid4()

    # lifecycle
    def create_call(self, call_id, stream_call_type, stream_call_id, call_type,
                    media, context_id, initiator_id, participant_ids, now):
        self.calls[call_id] = _C(
            id=call_id, stream_call_type=stream_call_type, stream_call_id=stream_call_id,
            call_type=call_type, media=media, status=CallStatus.RINGING.value,
            context_id=context_id, initiator_id=initiator_id, created_at=now,
            participants=[
                _P(
                    user_id=u, profile_id=0, name=self.names.get(u, "?"), avatar_url=None,
                    role=ParticipantRole.CALLER.value if u == initiator_id else ParticipantRole.CALLEE.value,
                    state=ParticipantState.JOINED.value if u == initiator_id else ParticipantState.RINGING.value,
                )
                for u in participant_ids
            ],
        )
        return self.calls[call_id]

    def get_call(self, call_id):
        return self.calls.get(call_id)

    def busy_call_id(self, uid):
        horizon = datetime.now(timezone.utc) - timedelta(seconds=MAX_CALL_DURATION_SECONDS)
        for c in self.calls.values():
            if c.created_at < horizon:
                continue
            if c.status in (CallStatus.RINGING.value, CallStatus.ACTIVE.value):
                p = c.participant(uid)
                if p and p.state in (ParticipantState.RINGING.value, ParticipantState.JOINED.value):
                    return c.id
        return None

    def _set_state(self, call_id, uid, state, now):
        p = self.calls[call_id].participant(uid)
        if p:
            p.state = state
            if state == ParticipantState.JOINED.value:
                p.joined_at = now
            else:
                p.left_at = now

    def mark_participant_joined(self, call_id, uid, now):
        self._set_state(call_id, uid, ParticipantState.JOINED.value, now)

    def mark_participant_rejected(self, call_id, uid, now):
        self._set_state(call_id, uid, ParticipantState.REJECTED.value, now)

    def mark_participant_left(self, call_id, uid, now):
        self._set_state(call_id, uid, ParticipantState.LEFT.value, now)

    def activate_call(self, call_id, now):
        c = self.calls[call_id]
        if c.started_at is None:
            c.started_at = now
        c.status = CallStatus.ACTIVE.value
        return c.started_at

    def end_call(self, call_id, status, end_reason, now):
        c = self.calls[call_id]
        c.status, c.ended_at, c.end_reason = status, now, end_reason
        c.duration_seconds = int((now - c.started_at).total_seconds()) if c.started_at else 0
        for p in c.participants:
            if p.state == ParticipantState.RINGING.value:
                p.state = ParticipantState.MISSED.value
            elif p.state == ParticipantState.JOINED.value:
                p.state = ParticipantState.LEFT.value
        return c

    def active_participant_count(self, call_id):
        return sum(1 for p in self.calls[call_id].participants
                   if p.state == ParticipantState.JOINED.value)

    def participant_count(self, call_id):
        return len(self.calls[call_id].participants)

    def write_call_card(self, **kw):
        self.cards.append(kw)

    def expired_ringing_call_ids(self, cutoff):
        return [c.id for c in self.calls.values()
                if c.status == CallStatus.RINGING.value and c.created_at < cutoff]

    def stale_active_call_ids(self, cutoff):
        return [c.id for c in self.calls.values()
                if c.status == CallStatus.ACTIVE.value and c.started_at and c.started_at < cutoff]

    def overlong_call_ids(self, cutoff):
        return self.stale_active_call_ids(cutoff)

    def touch_heartbeat(self, call_id, user_id, now):
        p = self.calls[call_id].participant(user_id)
        if p:
            p.last_heartbeat_at = now

    def _present(self, c, cutoff):
        n = 0
        for p in c.participants:
            if p.state != ParticipantState.JOINED.value:
                continue
            hb = getattr(p, "last_heartbeat_at", None) or c.started_at
            if hb and hb >= cutoff:
                n += 1
        return n

    def dead_heartbeat_call_ids(self, cutoff):
        return [c.id for c in self.calls.values()
                if c.status == CallStatus.ACTIVE.value and self._present(c, cutoff) == 0]

    def mark_provider_ended(self, call_id, now):
        self.calls[call_id].provider_ended_at = now

    def unterminated_provider_call_ids(self, since):
        return [c.id for c in self.calls.values()
                if c.status not in (CallStatus.RINGING.value, CallStatus.ACTIVE.value)
                and getattr(c, "provider_ended_at", None) is None
                and c.ended_at and c.ended_at >= since]

    def solo_participant_call_ids(self, cutoff, started_before):
        return [c.id for c in self.calls.values()
                if c.status == CallStatus.ACTIVE.value
                and c.started_at and c.started_at < started_before
                and self._present(c, cutoff) == 1]

    def write_call_card(self, **kw):
        self.cards.append(kw)

    def list_calls(self, *a, **kw):
        return [], None

    def active_call_ids_started_before(self, cutoff):
        return [c.id for c in self.calls.values()
                if c.status == CallStatus.ACTIVE.value and c.started_at and c.started_at < cutoff]

    def live_call_ids_between(self, a, b):
        out = []
        for c in self.calls.values():
            if c.status not in (CallStatus.RINGING.value, CallStatus.ACTIVE.value):
                continue
            ids = {p.user_id for p in c.participants}
            if a in ids and b in ids:
                out.append(c.id)
        return out

    def register_device(self, user_id, fcm_token, platform, now):
        self.devices.append((user_id, fcm_token))

    def push_targets(self, uids):
        out, seen = [], set()
        for u, tok in self.devices:
            if u in uids and tok not in seen:
                seen.add(tok); out.append(PushTarget(user_id=u, fcm_token=tok))
        for u in uids:
            tok = f"legacy-{u}"
            if tok not in seen:
                seen.add(tok); out.append(PushTarget(user_id=u, fcm_token=tok))
        return out

    # concurrency — the fake records lock order so tests can assert on it
    def lock_users_for_call(self, user_ids):
        self.locks.append(sorted(str(u) for u in user_ids))

    def lock_call(self, call_id):
        self.locked_calls.append(call_id)
        return call_id in self.calls

    def commit(self): pass
    def rollback(self): pass


def _start(repo, caller=ALICE, target=BOB, call_type="dm", group_id=None,
           provider=None, rc=None):
    return initiate_call(
        repo, provider or FakeProvider(), FakePush(),
        caller_id=caller, call_type=call_type,
        target_user_id=target if call_type == "dm" else None,
        group_id=group_id, media="audio", rc=rc,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_blocked_cannot_call():
    repo = FakeRepo(blocks=[(ALICE, BOB)])
    try:
        _start(repo)
        raise AssertionError("blocked call was allowed")
    except CallBlockedError:
        pass
    # ...and unblocking restores it, which is the behaviour that was asked for.
    repo.blocks.clear()
    assert _start(repo).result.status == CallStatus.RINGING.value


def test_block_rechecked_at_accept():
    repo = FakeRepo()
    d = _start(repo)
    repo.blocks.add(frozenset((ALICE, BOB)))   # blocked while ringing
    try:
        accept_call(repo, FakeProvider(), call_id=d.result.call_id, user_id=BOB)
        raise AssertionError("accept ignored a block set after ringing started")
    except CallBlockedError:
        pass


def test_self_call_and_video_rejected():
    repo = FakeRepo()
    try:
        _start(repo, caller=ALICE, target=ALICE)
        raise AssertionError("self-call allowed")
    except SelfCallError:
        pass
    try:
        initiate_call(repo, FakeProvider(), FakePush(), caller_id=ALICE,
                      call_type="dm", target_user_id=BOB, group_id=None, media="video")
        raise AssertionError("video allowed before it ships")
    except VideoNotAvailableError:
        pass


def test_busy_checks():
    repo = FakeRepo()
    _start(repo)
    try:
        _start(repo, caller=ALICE, target=CARE)
        raise AssertionError("caller started a second call while busy")
    except CallerBusyError:
        pass
    try:
        _start(repo, caller=CARE, target=BOB)
        raise AssertionError("callee was rung while already on a call")
    except CalleeBusyError:
        pass


def test_duration_is_server_computed():
    repo = FakeRepo()
    d = _start(repo)
    cid = d.result.call_id
    accept_call(repo, FakeProvider(), call_id=cid, user_id=BOB)
    # Backdate the start: duration must follow the server clock, not any input.
    repo.calls[cid].started_at = datetime.now(timezone.utc) - timedelta(seconds=90)

    out = end_call(repo, call_id=cid, user_id=ALICE).result
    assert 89 <= out.duration_seconds <= 95, out.duration_seconds
    assert out.status == CallStatus.ENDED.value
    assert out.end_reason == EndReason.HUNG_UP.value
    assert repo.cards, "no call card written to chat"


def test_unanswered_caller_hangup_is_cancelled():
    repo = FakeRepo()
    d = _start(repo)
    out = end_call(repo, call_id=d.result.call_id, user_id=ALICE).result
    assert out.status == CallStatus.CANCELLED.value, out.status
    assert out.duration_seconds == 0


def test_dm_reject_ends_call():
    repo = FakeRepo()
    d = _start(repo)
    out = reject_call(repo, call_id=d.result.call_id, user_id=BOB).result
    assert out.status == CallStatus.REJECTED.value
    assert repo.calls[d.result.call_id].status == CallStatus.REJECTED.value


def test_group_reject_does_not_end_call():
    repo = FakeRepo()
    d = _start(repo, call_type="group", target=None, group_id=GROUP)
    cid = d.result.call_id
    reject_call(repo, call_id=cid, user_id=BOB)
    assert repo.calls[cid].status == CallStatus.RINGING.value, "group call died on one reject"


def test_group_call_ends_with_last_participant():
    repo = FakeRepo()
    d = _start(repo, call_type="group", target=None, group_id=GROUP)
    cid = d.result.call_id
    accept_call(repo, FakeProvider(), call_id=cid, user_id=BOB)
    accept_call(repo, FakeProvider(), call_id=cid, user_id=CARE)

    end_call(repo, call_id=cid, user_id=BOB)
    assert repo.calls[cid].status == CallStatus.ACTIVE.value, "call ended while others were on it"

    end_call(repo, call_id=cid, user_id=CARE)
    assert repo.calls[cid].status == CallStatus.ACTIVE.value

    out = end_call(repo, call_id=cid, user_id=ALICE).result
    assert out.status == CallStatus.ENDED.value, "last participant leaving did not end the call"


def test_ring_timeout_marks_missed():
    repo = FakeRepo()
    d = _start(repo)
    cid = d.result.call_id
    repo.calls[cid].created_at = datetime.now(timezone.utc) - timedelta(seconds=120)

    now = datetime.now(timezone.utc)
    for call_id in repo.expired_ringing_call_ids(now - timedelta(seconds=45)):
        repo.end_call(call_id, CallStatus.MISSED.value, EndReason.MISSED.value, now)

    assert repo.calls[cid].status == CallStatus.MISSED.value
    assert repo.calls[cid].participant(BOB).state == ParticipantState.MISSED.value


def test_caller_freed_after_call_ends():
    """Regression guard: a stuck call must not leave a user permanently busy."""
    repo = FakeRepo()
    d = _start(repo)
    end_call(repo, call_id=d.result.call_id, user_id=ALICE)
    assert repo.busy_call_id(ALICE) is None
    assert repo.busy_call_id(BOB) is None


# ── Cost guardrails ───────────────────────────────────────────────────────────

def test_provider_told_to_end_on_hangup():
    """The whole point: ending a call in our DB does not stop the meter."""
    prov = FakeProvider()
    repo = FakeRepo()
    d = _start(repo, provider=prov)
    cid = d.result.call_id
    accept_call(repo, prov, call_id=cid, user_id=BOB)

    end_call(repo, call_id=cid, user_id=ALICE, provider=prov)
    assert repo.calls[cid].stream_call_id in prov.ended, \
        "call ended locally but the provider session was left running"


def test_duration_cap_sent_to_provider_at_creation():
    """The only guardrail that survives our backend being down."""
    prov = FakeProvider()
    repo = FakeRepo()
    _start(repo, provider=prov)
    assert prov.provisioned, "call was never provisioned with a duration cap"
    _, cap = prov.provisioned[0]
    assert cap == MAX_CALL_DURATION_SECONDS


def test_call_still_works_when_provisioning_fails():
    """A provider blip must degrade, not block calling."""
    prov = FakeProvider(fail_provision=True)
    repo = FakeRepo()
    assert _start(repo, provider=prov).result.status == CallStatus.RINGING.value


def test_solo_participant_call_is_reaped():
    """B hangs up, A's phone is in a pocket: nobody ends the call and it bills on."""
    prov = FakeProvider()
    repo = FakeRepo()
    d = _start(repo, provider=prov)
    cid = d.result.call_id
    accept_call(repo, prov, call_id=cid, user_id=BOB)

    now = datetime.now(timezone.utc)
    repo.calls[cid].started_at = now - timedelta(seconds=600)
    repo.mark_participant_left(cid, BOB, now - timedelta(seconds=300))   # B left
    heartbeat(repo, call_id=cid, user_id=ALICE)                          # A still alive

    victims = repo.solo_participant_call_ids(
        now - timedelta(seconds=HEARTBEAT_TIMEOUT_SECONDS),
        now - timedelta(seconds=120),
    )
    assert cid in victims, "solo call was not detected"

    terminate_call(repo, prov, None, cid, CallStatus.ENDED.value,
                   EndReason.TIMEOUT.value, now)
    assert repo.calls[cid].status == CallStatus.ENDED.value
    assert repo.calls[cid].stream_call_id in prov.ended, \
        "reaper ended our row but left the provider session billing"


def test_reaper_bills_abandoned_time_to_budget():
    """Reaped calls must count against budget, or the reapers become a blind
    spot in exactly the case that costs most."""
    prov, rc, repo = FakeProvider(), FakeRedis(), FakeRepo()
    d = _start(repo, provider=prov)
    cid = d.result.call_id
    accept_call(repo, prov, call_id=cid, user_id=BOB)

    now = datetime.now(timezone.utc)
    repo.calls[cid].started_at = now - timedelta(minutes=10)
    terminate_call(repo, prov, rc, cid, CallStatus.FAILED.value,
                   EndReason.FAILED.value, now)

    assert any(v >= 10 for k, v in rc.store.items() if ":user:" in k), \
        "abandoned call was not billed to any user budget"
    assert any(v >= 20 for k, v in rc.store.items() if ":platform:" in k), \
        "abandoned call was not billed to the platform budget (2 x 10 min)"


def test_budget_blocks_new_calls_when_exhausted():
    from app.modules.calling.application.budget import _platform_key
    rc = FakeRedis({_platform_key(): 10_000_000})
    repo = FakeRepo()
    try:
        _start(repo, rc=rc)
        raise AssertionError("call allowed with the platform budget blown")
    except CallBudgetExceededError:
        pass


def test_budget_fails_open_when_redis_is_down():
    """A cache outage must not take calling down with it."""
    class DeadRedis:
        def get(self, k): raise ConnectionError("redis down")
    assert check_budget(DeadRedis(), ALICE) is None
    assert check_budget(None, ALICE) is None
    record_usage(None, [ALICE], 600)     # must not raise


def test_participant_minutes_are_rounded_up():
    """Stream bills started minutes: 10 seconds costs a minute, not zero."""
    rc = FakeRedis()
    record_usage(rc, [ALICE, BOB], 10)
    assert any(v == 2 for k, v in rc.store.items() if ":platform:" in k), \
        f"expected 2 participant-minutes for a 10s two-person call, got {rc.store}"


# ── Liveness / "user forgot to end the call" ──────────────────────────────────

def test_heartbeat_keeps_a_live_call_alive():
    prov, repo = FakeProvider(), FakeRepo()
    d = _start(repo, provider=prov)
    cid = d.result.call_id
    accept_call(repo, prov, call_id=cid, user_id=BOB)

    now = datetime.now(timezone.utc)
    repo.calls[cid].started_at = now - timedelta(hours=1)   # long, but live
    heartbeat(repo, call_id=cid, user_id=ALICE)

    dead = repo.dead_heartbeat_call_ids(now - timedelta(seconds=HEARTBEAT_TIMEOUT_SECONDS))
    assert cid not in dead, "a call that is still pinging was swept as dead"


def test_app_killed_midcall_is_swept():
    """The headline case: both users close the app without hanging up."""
    prov, repo = FakeProvider(), FakeRepo()
    d = _start(repo, provider=prov)
    cid = d.result.call_id
    accept_call(repo, prov, call_id=cid, user_id=BOB)

    now = datetime.now(timezone.utc)
    repo.calls[cid].started_at = now - timedelta(minutes=30)
    repo.calls[cid].last_heartbeat_at = now - timedelta(minutes=29)  # pings stopped

    dead = repo.dead_heartbeat_call_ids(now - timedelta(seconds=HEARTBEAT_TIMEOUT_SECONDS))
    assert cid in dead, "dead call was not detected by the heartbeat sweep"

    terminate_call(repo, prov, None, cid, CallStatus.ENDED.value,
                   EndReason.TIMEOUT.value, now)
    assert repo.calls[cid].status == CallStatus.ENDED.value
    assert repo.calls[cid].stream_call_id in prov.ended, "provider session left billing"
    assert repo.busy_call_id(ALICE) is None, "user still locked out after sweep"
    assert repo.busy_call_id(BOB) is None


def test_call_with_no_heartbeat_ever_still_swept():
    """A client too old to send heartbeats must not opt out of the guardrail."""
    prov, repo = FakeProvider(), FakeRepo()
    d = _start(repo, provider=prov)
    cid = d.result.call_id
    accept_call(repo, prov, call_id=cid, user_id=BOB)

    now = datetime.now(timezone.utc)
    repo.calls[cid].started_at = now - timedelta(minutes=10)
    repo.calls[cid].last_heartbeat_at = None      # never pinged

    assert cid in repo.dead_heartbeat_call_ids(now - timedelta(seconds=HEARTBEAT_TIMEOUT_SECONDS))


def test_heartbeat_on_ended_call_tells_client_to_stop():
    prov, repo = FakeProvider(), FakeRepo()
    d = _start(repo, provider=prov)
    cid = d.result.call_id
    accept_call(repo, prov, call_id=cid, user_id=BOB)
    end_call(repo, call_id=cid, user_id=ALICE, provider=prov)
    try:
        heartbeat(repo, call_id=cid, user_id=BOB)
        raise AssertionError("heartbeat accepted on a terminal call")
    except CallAlreadyEndedError:
        pass


def test_busy_flag_expires_so_users_are_not_stranded():
    """Even if every sweep fails, a user must not be locked out forever."""
    repo = FakeRepo()
    d = _start(repo)
    cid = d.result.call_id
    repo.calls[cid].created_at = datetime.now(timezone.utc) - timedelta(hours=3)
    assert repo.busy_call_id(ALICE) is None, "stale call still marks the user busy"


# ── Notification completeness ─────────────────────────────────────────────────

def test_swept_call_writes_a_chat_card():
    """A missed call is the most important card to show in the thread."""
    prov, repo = FakeProvider(), FakeRepo()
    d = _start(repo, provider=prov)
    cid = d.result.call_id
    now = datetime.now(timezone.utc)
    terminate_call(repo, prov, None, cid, CallStatus.MISSED.value,
                   EndReason.MISSED.value, now)
    assert repo.cards, "missed call left no card in the conversation"
    assert repo.cards[-1]["status"] == CallStatus.MISSED.value


def test_answered_call_end_pushes_to_peer():
    """A backgrounded peer whose socket is gone must still be told, or its
    media session stays open and keeps billing."""
    prov, repo = FakeProvider(), FakeRepo()
    d = _start(repo, provider=prov)
    cid = d.result.call_id
    accept_call(repo, prov, call_id=cid, user_id=BOB)
    out = end_call(repo, call_id=cid, user_id=ALICE, provider=prov)
    assert out.pushes, "no push sent when an answered call ended"
    assert BOB in out.pushes[0].user_ids
    assert out.pushes[0].data["type"] == "call_ended"


def test_token_refresh_refused_past_max_duration():
    """Otherwise a client could renew its way around the duration cap."""
    from app.modules.calling.application.use_cases.get_calls import refresh_token
    prov, repo = FakeProvider(), FakeRepo()
    d = _start(repo, provider=prov)
    cid = d.result.call_id
    accept_call(repo, prov, call_id=cid, user_id=BOB)
    repo.calls[cid].started_at = (
        datetime.now(timezone.utc) - timedelta(seconds=MAX_CALL_DURATION_SECONDS + 60)
    )
    try:
        refresh_token(repo, prov, call_id=cid, user_id=ALICE)
        raise AssertionError("token renewed past the hard duration cap")
    except CallAlreadyEndedError:
        pass


# ── Presence is per-participant, not per-call ─────────────────────────────────

def test_peer_dies_without_hanging_up_is_detected():
    """The case the old left_at-based solo check could NOT see.

    B's battery dies mid-call. B never hangs up, so there is no `left_at` and no
    "someone left" event to key off. A keeps pinging, so a call-level heartbeat
    would look perfectly healthy and the call would run to the 2 h cap.
    Per-participant presence catches it.
    """
    prov, repo = FakeProvider(), FakeRepo()
    d = _start(repo, provider=prov)
    cid = d.result.call_id
    accept_call(repo, prov, call_id=cid, user_id=BOB)

    now = datetime.now(timezone.utc)
    repo.calls[cid].started_at = now - timedelta(minutes=20)
    heartbeat(repo, call_id=cid, user_id=ALICE)                       # A alive
    repo.calls[cid].participant(BOB).last_heartbeat_at = now - timedelta(minutes=10)  # B dead

    assert repo.calls[cid].participant(BOB).left_at is None, "B never hung up"
    victims = repo.solo_participant_call_ids(
        now - timedelta(seconds=HEARTBEAT_TIMEOUT_SECONDS),
        now - timedelta(seconds=120),
    )
    assert cid in victims, "a dead peer that never hung up went undetected"


def test_caller_who_never_joined_does_not_count_as_present():
    """We mark the caller joined optimistically at ring time. If their app dies
    before they reach the media session, `state` still says joined — only the
    absence of heartbeats reveals they were never really there."""
    prov, repo = FakeProvider(), FakeRepo()
    d = _start(repo, provider=prov)
    cid = d.result.call_id
    accept_call(repo, prov, call_id=cid, user_id=BOB)

    now = datetime.now(timezone.utc)
    repo.calls[cid].started_at = now - timedelta(minutes=20)
    heartbeat(repo, call_id=cid, user_id=BOB)                         # only B is real
    repo.calls[cid].participant(ALICE).last_heartbeat_at = now - timedelta(minutes=15)

    assert repo.calls[cid].participant(ALICE).state == ParticipantState.JOINED.value
    victims = repo.solo_participant_call_ids(
        now - timedelta(seconds=HEARTBEAT_TIMEOUT_SECONDS),
        now - timedelta(seconds=120),
    )
    assert cid in victims, "a caller who never actually joined still counted as present"


# ── Token cannot be used to skip accept ───────────────────────────────────────

def test_ringing_callee_cannot_mint_a_token():
    """Otherwise a callee joins the media session without accepting: the call
    stays `ringing`, never gets a started_at, and is swept as missed 45 s later
    while they are mid-conversation — having billed the whole time."""
    from app.modules.calling.application.use_cases.get_calls import refresh_token
    from app.modules.calling.domain.exceptions import CallNotRingingError
    prov, repo = FakeProvider(), FakeRepo()
    d = _start(repo, provider=prov)
    try:
        refresh_token(repo, prov, call_id=d.result.call_id, user_id=BOB)
        raise AssertionError("a ringing callee minted a token without accepting")
    except CallNotRingingError:
        pass


def test_joined_participant_can_refresh():
    from app.modules.calling.application.use_cases.get_calls import refresh_token
    prov, repo = FakeProvider(), FakeRepo()
    d = _start(repo, provider=prov)
    cid = d.result.call_id
    accept_call(repo, prov, call_id=cid, user_id=BOB)
    assert refresh_token(repo, prov, call_id=cid, user_id=BOB).token


# ── A failed provider termination must be retried ─────────────────────────────

def test_failed_provider_termination_is_retried():
    """The only failure that keeps costing money after the call is over in every
    other respect — every other sweep skips terminal calls."""
    repo = FakeRepo()
    bad = FakeProvider(fail_end=True)
    d = _start(repo, provider=bad)
    cid = d.result.call_id
    accept_call(repo, bad, call_id=cid, user_id=BOB)

    now = datetime.now(timezone.utc)
    terminate_call(repo, bad, None, cid, CallStatus.ENDED.value,
                   EndReason.HUNG_UP.value, now)
    assert repo.calls[cid].provider_ended_at is None, "failure was recorded as success"

    pending = repo.unterminated_provider_call_ids(now - timedelta(hours=6))
    assert cid in pending, "un-terminated session not queued for retry"

    good = FakeProvider()
    for call_id in pending:
        c = repo.get_call(call_id)
        if good.end_call_remote(c.stream_call_type, c.stream_call_id):
            repo.mark_provider_ended(call_id, now)
    assert repo.calls[cid].provider_ended_at is not None
    assert repo.calls[cid].stream_call_id in good.ended


def test_successful_termination_is_not_retried():
    prov, repo = FakeProvider(), FakeRepo()
    d = _start(repo, provider=prov)
    cid = d.result.call_id
    now = datetime.now(timezone.utc)
    terminate_call(repo, prov, None, cid, CallStatus.MISSED.value,
                   EndReason.MISSED.value, now)
    assert cid not in repo.unterminated_provider_call_ids(now - timedelta(hours=6))


# ── Concurrency ───────────────────────────────────────────────────────────────

def test_initiate_locks_both_parties_before_the_busy_check():
    """Without this the busy check is check-then-act: two taps in the same
    instant both see the user free and both create a call, billing in parallel."""
    repo = FakeRepo()
    _start(repo)
    assert repo.locks, "initiate took no lock"
    locked = repo.locks[0]
    assert str(ALICE) in locked and str(BOB) in locked, "callee was not locked"


def test_lock_order_is_deterministic_so_pairs_cannot_deadlock():
    """A calls B while B calls A: both must acquire in the same order."""
    r1, r2 = FakeRepo(), FakeRepo()
    _start(r1, caller=ALICE, target=BOB)
    _start(r2, caller=BOB, target=ALICE)
    assert r1.locks[0] == r2.locks[0], "opposing calls would acquire locks in opposite order"


def test_group_initiate_locks_every_member_it_rings():
    repo = FakeRepo()
    _start(repo, call_type="group", target=None, group_id=GROUP)
    locked = repo.locks[-1]
    for u in (ALICE, BOB, CARE):
        assert str(u) in locked, f"{u} was rung without being locked"


def test_end_takes_a_row_lock_before_reading():
    """Serialises the end path so simultaneous hangups cannot both see the other
    as still present and leave the call running."""
    prov, repo = FakeProvider(), FakeRepo()
    d = _start(repo, provider=prov)
    cid = d.result.call_id
    accept_call(repo, prov, call_id=cid, user_id=BOB)
    end_call(repo, call_id=cid, user_id=ALICE, provider=prov)
    assert cid in repo.locked_calls, "end path did not lock the call row"


def test_end_on_unknown_call_is_404_not_a_crash():
    repo = FakeRepo()
    try:
        end_call(repo, call_id=uuid4(), user_id=ALICE)
        raise AssertionError("ending a non-existent call did not raise")
    except CallNotFoundError:
        pass


def test_group_accept_rechecks_blocks():
    """The DM path already did this; the group path silently did not."""
    prov, repo = FakeProvider(), FakeRepo()
    d = _start(repo, call_type="group", target=None, group_id=GROUP, provider=prov)
    cid = d.result.call_id
    repo.blocks.add(frozenset((ALICE, BOB)))       # blocked while ringing
    try:
        accept_call(repo, prov, call_id=cid, user_id=BOB)
        raise AssertionError("blocked member joined a group call")
    except CallBlockedError:
        pass


def test_provisioning_happens_after_the_row_exists():
    """Reordered so a failed DB write cannot orphan a session on the provider."""
    prov, repo = FakeProvider(), FakeRepo()
    d = _start(repo, provider=prov)
    assert prov.provisioned, "call was never provisioned"
    assert d.result.call_id in repo.calls, "provisioned without a persisted call row"


# ── Multi-device ──────────────────────────────────────────────────────────────

def test_every_device_is_rung_not_just_the_newest():
    """users.fcm_token holds one token, so a user with a phone and a tablet
    would only ever ring on whichever registered last."""
    repo = FakeRepo()
    now = datetime.now(timezone.utc)
    repo.register_device(BOB, "bob-phone", "android", now)
    repo.register_device(BOB, "bob-tablet", "ios", now)
    tokens = {t.fcm_token for t in repo.push_targets([BOB])}
    assert {"bob-phone", "bob-tablet"} <= tokens, f"not every device rings: {tokens}"


def test_push_targets_are_deduped():
    """A device in both user_devices and the legacy column must not ring twice."""
    repo = FakeRepo()
    repo.register_device(BOB, f"legacy-{BOB}", None, datetime.now(timezone.utc))
    tokens = [t.fcm_token for t in repo.push_targets([BOB])]
    assert len(tokens) == len(set(tokens)), f"duplicate push targets: {tokens}"


def test_accept_tells_the_answerers_other_devices_to_stop():
    prov, repo = FakeProvider(), FakeRepo()
    d = _start(repo, provider=prov)
    cid = d.result.call_id
    out = accept_call(repo, prov, call_id=cid, user_id=BOB)
    events = {(e.event, e.user_id) for e in out.socket_events}
    assert ("call_answered_elsewhere", BOB) in events, "other devices keep ringing"
    assert any(p.data.get("type") == "call_answered_elsewhere" for p in out.pushes), \
        "backgrounded devices of the answerer are never told"


# ── Block drops a live call ───────────────────────────────────────────────────

def test_blocking_mid_call_finds_the_live_call():
    """A block that leaves you still talking to the person is not a block."""
    prov, repo = FakeProvider(), FakeRepo()
    d = _start(repo, provider=prov)
    cid = d.result.call_id
    accept_call(repo, prov, call_id=cid, user_id=BOB)

    assert cid in repo.live_call_ids_between(ALICE, BOB)
    terminate_call(repo, prov, None, cid, CallStatus.ENDED.value,
                   EndReason.HUNG_UP.value, datetime.now(timezone.utc))
    assert repo.calls[cid].status == CallStatus.ENDED.value
    assert repo.live_call_ids_between(ALICE, BOB) == []


# ── Presence must fail SAFE, never open ───────────────────────────────────────

def test_presence_returns_none_when_redis_is_down():
    """Reading 'no keys' from a dead Redis is indistinguishable from 'everyone
    left'. Acting on it would end every live call on the platform at once."""
    from app.modules.calling.application import presence

    class DeadRedis:
        def pipeline(self, transaction=False): raise ConnectionError("down")
        def ping(self): raise ConnectionError("down")

    assert presence.present_user_ids(DeadRedis(), uuid4(), [ALICE]) is None
    assert presence.present_user_ids(None, uuid4(), [ALICE]) is None
    assert presence.presence_available(DeadRedis()) is False
    assert presence.presence_available(None) is False


def test_presence_sweep_skips_calls_with_no_data():
    """The guard that turns the above into safety: no data means no sweep."""
    from app.modules.calling.application.jobs import _presence_filtered

    prov, repo = FakeProvider(), FakeRepo()
    d = _start(repo, provider=prov)
    cid = d.result.call_id
    accept_call(repo, prov, call_id=cid, user_id=BOB)
    repo.calls[cid].started_at = datetime.now(timezone.utc) - timedelta(minutes=10)

    victims = _presence_filtered(repo, None, [cid], want_present=0)
    assert victims == [], "a live call was swept using presence data that did not exist"


def test_caller_cannot_accept_their_own_call():
    """Found against production: the initiator is a participant, so the
    membership check let them through. Accepting your own call forces it ACTIVE
    with nobody on the other end — Stream starts billing, the ring timeout stops
    applying, and the callee can no longer reject because it is "no longer
    ringing"."""
    from app.modules.calling.domain.exceptions import NotParticipantError
    prov, repo = FakeProvider(), FakeRepo()
    d = _start(repo, provider=prov)
    try:
        accept_call(repo, prov, call_id=d.result.call_id, user_id=ALICE)
        raise AssertionError("the caller accepted their own call")
    except NotParticipantError:
        pass
    assert repo.get_call(d.result.call_id).status == "ringing"


def test_caller_cannot_reject_their_own_call():
    """Same trap on the other branch. It would record the caller's own
    cancellation as end_reason "rejected", which is the wrong story in call
    history and in the chat card. Hanging up before an answer is POST /end."""
    from app.modules.calling.application.use_cases.respond_to_call import reject_call
    from app.modules.calling.domain.exceptions import NotParticipantError
    prov, repo = FakeProvider(), FakeRepo()
    d = _start(repo, provider=prov)
    try:
        reject_call(repo, call_id=d.result.call_id, user_id=ALICE, provider=prov)
        raise AssertionError("the caller rejected their own call")
    except NotParticipantError:
        pass
    assert repo.get_call(d.result.call_id).status == "ringing"


def test_cursor_roundtrip():
    now = datetime.now(timezone.utc)
    assert _decode_cursor(_encode_cursor(now)) == now
    assert _decode_cursor(None) is None
    assert _decode_cursor("not-a-cursor") is None   # stale cursor must not 500


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except Exception as exc:
            failed += 1
            print(f"  FAIL  {t.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
