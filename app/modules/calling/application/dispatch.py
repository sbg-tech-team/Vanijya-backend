"""Side-effect descriptions returned by use cases.

Use cases are synchronous and must not perform I/O beyond the repository, so
instead of emitting sockets and pushes themselves they DESCRIBE what should be
sent. The router dispatches the result through BackgroundTasks — the same
pattern the post, chat and connections routers already use for `emit_to_user`.

This keeps the use cases unit-testable with no Redis, Socket.IO or FCM present.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True)
class SocketEvent:
    """One Socket.IO emit. `group_id` set => emit to the group room, else the
    per-user room."""
    event: str
    payload: dict
    user_id: UUID | None = None
    group_id: UUID | None = None


@dataclass(frozen=True)
class PushMessage:
    """One data-only FCM fan-out."""
    user_ids: list[UUID]
    data: dict


@dataclass(frozen=True)
class ProviderCall:
    """A call to the video provider whose result the caller never needs —
    run after the response via background_tasks instead of inline/blocking
    it. See initiate_call's provision_call and reject_call's DM-branch
    end_call_remote: both are already best-effort, their return value was
    never checked even when called synchronously."""
    method: str
    kwargs: dict = field(default_factory=dict)


@dataclass
class CallDispatch:
    """Whatever the caller should return, plus the side effects to fire after."""
    result: object
    socket_events: list[SocketEvent] = field(default_factory=list)
    pushes: list[PushMessage] = field(default_factory=list)
    provider_calls: list[ProviderCall] = field(default_factory=list)
