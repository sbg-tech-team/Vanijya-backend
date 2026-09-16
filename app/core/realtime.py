"""Socket.IO server + emit helpers — shared real-time infrastructure.

Lives in core/, not in a module's presentation layer: chat, calling, groups,
post, news and connections all need to push events, and a module reaching into
another module's presentation layer to do it is a layering violation.

Module-specific socket *handlers* (chat typing, delivery receipts, …) stay in
their own module's presentation layer and import `sio` from here.

⚠️  SINGLE-WORKER ONLY. State here lives in-process:
  • `_sid_user` is a plain in-memory dict (not shared across processes), and
  • `sio` uses the default in-memory client manager (no message queue).

So room membership and `emit_to_user` / `is_online` only see sockets connected
to *this* process. HTTP handlers emit from background tasks in whatever worker
served the request — if that's a different worker than the one holding the
recipient's socket, the push is silently dropped.

➡️  Run the app with a SINGLE worker (e.g. `uvicorn ... --workers 1`). To scale
to multiple workers later, give socketio a shared backend
(`socketio.AsyncRedisManager(...)`) and move `_sid_user` into Redis.
"""
import asyncio
import logging
from uuid import UUID

import socketio

from app.core.security.jwt_handler import decode_access_token

sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')

# sid → str(user_id) — needed to verify group membership in join_group
_sid_user: dict[str, str] = {}

# str(user_id) → {sid, ...} — the reverse map. Needed to evict a user from a
# group room when they leave, are removed, or are frozen: without it their
# socket stays in `group:{id}` and keeps receiving messages and call events
# after the REST layer has correctly cut them off. One user can hold several
# sids (multiple tabs/devices), so this is a set.
_user_sids: dict[str, set[str]] = {}

_log = logging.getLogger(__name__)

# The event loop Socket.IO runs on. APScheduler jobs execute in worker THREADS
# with no running loop, so a job that needs to emit has to hand the coroutine
# back to this loop. Captured on first connect — if nobody has ever connected
# there is nobody to emit to, so None is the correct no-op.
_loop: asyncio.AbstractEventLoop | None = None


def user_for_sid(sid: str) -> str | None:
    """str(user_id) behind a socket, or None if it is not authenticated."""
    return _sid_user.get(sid)


@sio.event
async def connect(sid, _environ, auth):
    try:
        token = auth.get("token")
        decoded_token = decode_access_token(token)
    except Exception:
        return False
    global _loop
    if _loop is None:
        _loop = asyncio.get_running_loop()
    user_id = str(decoded_token.user_id)
    _sid_user[sid] = user_id
    _user_sids.setdefault(user_id, set()).add(sid)
    await sio.enter_room(sid, f"user:{user_id}")


@sio.event
async def disconnect(sid):
    user_id = _sid_user.pop(sid, None)
    if user_id is not None:
        sids = _user_sids.get(user_id)
        if sids is not None:
            sids.discard(sid)
            if not sids:
                _user_sids.pop(user_id, None)


async def evict_from_group_room(user_id: UUID, group_id: UUID) -> None:
    """Remove every socket this user holds from a group's room.

    Call this whenever someone stops being an active member — leaving, being
    removed, or being frozen. The REST layer already refuses them, but the room
    membership is what decides who receives `new_group_message`,
    `new_group_deal` and the call events, and nothing else ever revokes it.

    Best-effort: a socket that has already gone is not an error.
    """
    room = f"group:{group_id}"
    for sid in list(_user_sids.get(str(user_id), set())):
        try:
            await sio.leave_room(sid, room)
        except Exception:
            continue


async def evict_many_from_group_room(user_ids: list[UUID], group_id: UUID) -> None:
    """Bulk form of evict_from_group_room — used when a group is deleted."""
    for uid in user_ids:
        await evict_from_group_room(uid, group_id)


def emit_threadsafe(coro) -> None:
    """Schedule an emit coroutine onto the Socket.IO loop from a worker thread.

    Background jobs (ring timeout, heartbeat sweep, reapers) run under
    APScheduler in plain threads. Without this they cannot notify anyone, which
    would leave a caller staring at a ringing screen for a call the backend has
    already marked missed.
    """
    if _loop is None:
        coro.close()
        return
    try:
        asyncio.run_coroutine_threadsafe(coro, _loop)
    except Exception as exc:
        coro.close()
        _log.warning("threadsafe emit failed: %s", exc)


async def emit_to_user(user_id: UUID, event: str, data: dict) -> None:
    await sio.emit(event, data, room=f"user:{user_id}")


async def emit_to_group(group_id: UUID, event: str, data: dict) -> None:
    await sio.emit(event, data, room=f"group:{group_id}")


def is_online(user_id: UUID) -> bool:
    return bool(list(sio.manager.get_participants('/', f'user:{user_id}')))
