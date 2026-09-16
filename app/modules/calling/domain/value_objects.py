"""Calling value objects — pure Python, no I/O, no framework imports."""
from __future__ import annotations

from enum import Enum


class CallType(str, Enum):
    DM = "dm"
    GROUP = "group"


class CallMedia(str, Enum):
    AUDIO = "audio"
    VIDEO = "video"      # accepted by the schema, rejected with 501 until video ships


class CallStatus(str, Enum):
    RINGING = "ringing"
    ACTIVE = "active"
    ENDED = "ended"
    REJECTED = "rejected"
    MISSED = "missed"
    CANCELLED = "cancelled"
    FAILED = "failed"


#: Once a call reaches one of these, every mutating endpoint returns 409.
TERMINAL_STATUSES: frozenset[str] = frozenset({
    CallStatus.ENDED.value,
    CallStatus.REJECTED.value,
    CallStatus.MISSED.value,
    CallStatus.CANCELLED.value,
    CallStatus.FAILED.value,
})

#: A user may only hold one call in one of these states at a time.
BUSY_STATUSES: frozenset[str] = frozenset({
    CallStatus.RINGING.value,
    CallStatus.ACTIVE.value,
})


class EndReason(str, Enum):
    HUNG_UP = "hung_up"
    MISSED = "missed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    FAILED = "failed"


class ParticipantState(str, Enum):
    INVITED = "invited"
    RINGING = "ringing"
    JOINED = "joined"
    LEFT = "left"
    REJECTED = "rejected"
    MISSED = "missed"


class ParticipantRole(str, Enum):
    CALLER = "caller"
    CALLEE = "callee"


# ── Tunables ──────────────────────────────────────────────────────────────────

#: Seconds a call rings before the sweeper marks it missed.
RING_TIMEOUT_SECONDS: int = 45

#: Max participants in a group call. Audio-only; tune once real usage is known.
MAX_CALL_PARTICIPANTS: int = 20

#: Stream token lifetime. Clients refresh via POST /calls/{id}/token before this.
STREAM_TOKEN_TTL_SECONDS: int = 3600

# ── Runaway-cost guardrails ───────────────────────────────────────────────────
# Stream bills participants x wall-clock minutes, so an unended call bills
# forever. These are layered deliberately: each one catches what the one before
# it misses, and the first is enforced by Stream rather than by us.
#
#   1. MAX_CALL_DURATION_SECONDS  — sent to Stream as max_duration_seconds.
#      Stream ends the session itself, so this holds even if our backend is
#      completely down. This is the only cap that survives an outage.
#   2. SOLO_PARTICIPANT_TIMEOUT   — one person alone on a call has nobody to
#      talk to. Almost always a peer that crashed without sending `end`.
#   3. STALE_CALL_TIMEOUT         — absolute backstop for anything the above
#      missed. Should essentially never fire; if it does, something is wrong.

#: Hard ceiling on a single call. Also sent to Stream at provisioning time.
MAX_CALL_DURATION_SECONDS: int = 2 * 3600

#: Clients ping POST /calls/{id}/heartbeat on this interval while in a call.
HEARTBEAT_INTERVAL_SECONDS: int = 30

#: No heartbeat for this long means every client is gone — crashed, force-quit,
#: or out of battery. This is the ONLY signal that distinguishes "still talking"
#: from "app is dead", and it is what stops a forgotten call both from billing
#: and from leaving its participants marked busy.
HEARTBEAT_TIMEOUT_SECONDS: int = 90

#: A call left with a single joined participant for this long is ended. Their
#: peer died without hanging up, and the meter is running for nothing.
SOLO_PARTICIPANT_TIMEOUT_SECONDS: int = 120

#: How far back the provider-termination retry looks. Beyond this the provider's
#: own inactivity timeout has certainly fired, so retrying adds nothing.
PROVIDER_RETRY_WINDOW_SECONDS: int = 6 * 3600

#: A call stuck in `active` with no end signal for this long is reaped as failed.
#: Both clients can die without ever calling POST /calls/{id}/end.
STALE_CALL_TIMEOUT_SECONDS: int = 4 * 3600

#: Rate limit on call initiation, per user. Guards against cold-call spam, since
#: any user may call any other user (no relationship requirement).
INITIATE_RATE_LIMIT: int = 10
INITIATE_RATE_WINDOW_SECONDS: int = 3600
