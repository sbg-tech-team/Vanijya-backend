"""Chat-specific Socket.IO handlers.

Transport only. The Socket.IO server, room bookkeeping and the emit helpers are
shared infrastructure and live in `app.core.realtime`; every membership rule
below is decided by a use case against the repository interface.

Re-exports the emit helpers so `main.py` and existing chat code keep their
import site, but new code should import them from `app.core.realtime`.
"""
import logging
from uuid import UUID

from app.core.realtime import (  # noqa: F401  (re-exported for callers)
    emit_threadsafe,
    emit_to_group,
    emit_to_user,
    evict_from_group_room,
    evict_many_from_group_room,
    is_online,
    sio,
    user_for_sid,
)
from app.core.database.session import SessionLocal
from app.modules.chat.presentation.dependencies import build_socket_use_cases

_log = logging.getLogger(__name__)


def _with_use_cases(fn):
    """Run `fn(use_cases)` with a short-lived session — sockets get no request scope."""
    db = SessionLocal()
    try:
        return fn(build_socket_use_cases(db))
    finally:
        db.close()


@sio.event
async def join_group(sid, data):
    group_id = data.get("group_id")
    user_id = user_for_sid(sid)
    if not group_id or not user_id:
        return

    allowed = _with_use_cases(lambda uc: uc.can_join.execute(group_id, user_id))
    if not allowed:
        return  # silently refuse — not a member

    await sio.enter_room(sid, f"group:{group_id}")


@sio.event
async def typing(sid, data):
    await _relay_typing(sid, data, "typing")


@sio.event
async def stop_typing(sid, data):
    await _relay_typing(sid, data, "stop_typing")


async def _relay_typing(sid, data, event: str) -> None:
    """Relay a typing indicator to the DM peer or the group room (never echoed back)."""
    user_id = user_for_sid(sid)
    context_type = (data or {}).get("context_type")
    context_id = (data or {}).get("context_id")
    if not user_id or not context_type or not context_id:
        return

    payload = {"context_type": context_type, "context_id": str(context_id), "user_id": user_id}

    if context_type == "group":
        await sio.emit(event, payload, room=f"group:{context_id}", skip_sid=sid)
        return

    if context_type == "dm":
        peers = _with_use_cases(lambda uc: uc.relay_typing.execute(context_id, user_id))
        for mid in peers:
            await sio.emit(event, payload, room=f"user:{mid}")


@sio.event
async def message_delivered(sid, data):
    """Receiver acks that a DM's messages reached their device. Bumps this member's
    delivery high-water mark (last_delivered_at) and notifies the sender so they can
    flip their grey ticks. Cursor-based: one timestamp covers every message sent up to
    now, so the client acks once per batch — on receiving `new_message` and after a REST
    load of unseen messages (which covers the offline case)."""
    user_id = user_for_sid(sid)
    conv_id = (data or {}).get("conv_id")
    if not user_id or not conv_id:
        return

    result = _with_use_cases(lambda uc: uc.mark_delivered.execute(conv_id, user_id))
    if result is None:
        return  # not a member — ignore

    peer_id, now = result
    await sio.emit(
        "delivered",
        {"conv_id": str(conv_id), "delivered_to": user_id, "last_delivered_at": now.isoformat()},
        room=f"user:{peer_id}",
    )
