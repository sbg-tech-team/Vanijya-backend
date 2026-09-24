"""Socket.IO server + emit helpers — shared real-time infrastructure.

Lives in core/, not in a module's presentation layer: chat, calling, groups,
post, news and connections all need to push events, and a module reaching into
another module's presentation layer to do it is a layering violation.

Module-specific socket *handlers* (chat typing, delivery receipts, …) stay in
their own module's presentation layer and import `sio` from here.

Multi-worker safe when REDIS_URL is set:

  • emits fan out through `socketio.AsyncRedisManager`, so a handler in one
    worker reaches a socket held by another,
  • `is_online` reads a shared Redis set rather than this process's dict, and
  • room eviction is broadcast on a Redis channel, because a socket can only be
    removed from a room by the worker that owns it.

`_sid_user` / `_user_sids` stay process-local on purpose: a sid only ever exists
on one worker, so they are already correct per worker.

Without REDIS_URL it degrades to in-memory — correct for a single worker, and
silently lossy across several. That is the only configuration to avoid.
"""
import asyncio
import json
import logging
import os
from uuid import UUID

import socketio

from app.core.security.jwt_handler import decode_access_token

_log = logging.getLogger(__name__)

# Shared backend. Without it, two workers cannot see each other's sockets and
# every cross-worker push is dropped with no error.
_REDIS_URL = os.environ.get("REDIS_URL")
_client_manager = None
if _REDIS_URL:
    try:
        _client_manager = socketio.AsyncRedisManager(_REDIS_URL)
    except Exception as exc:  # bad URL, redis down at boot — do not block startup
        _log.warning("Socket.IO Redis manager unavailable, falling back to in-memory: %s", exc)

sio = socketio.AsyncServer(
    async_mode='asgi', cors_allowed_origins='*', client_manager=_client_manager,
)

# Cross-worker presence. `is_online` is called synchronously from routers, so
# this uses the sync client the rest of the app already uses.
_ONLINE_KEY = "rt:online:{}"
_ONLINE_TTL = 12 * 3600          # a socket that outlives this is already gone
_EVICT_CHANNEL = "rt:evict"


def _rc():
    try:
        from app.core.redis_client import get_redis
        return get_redis()
    except Exception:
        return None

# sid → str(user_id) — needed to verify group membership in join_group
_sid_user: dict[str, str] = {}

# str(user_id) → {sid, ...} — the reverse map. Needed to evict a user from a
# group room when they leave, are removed, or are frozen: without it their
# socket stays in `group:{id}` and keeps receiving messages and call events
# after the REST layer has correctly cut them off. One user can hold several
# sids (multiple tabs/devices), so this is a set.
_user_sids: dict[str, set[str]] = {}

# The event loop Socket.IO runs on. APScheduler jobs execute in worker THREADS
# with no running loop, so a job that needs to emit has to hand the coroutine
# back to this loop. Captured on first connect — if nobody has ever connected
# there is nobody to emit to, so None is the correct no-op.
_loop: asyncio.AbstractEventLoop | None = None

# The Redis eviction subscriber, cancelled on shutdown.
_evict_task: "asyncio.Task | None" = None


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
    _mark_online(user_id, sid, True)
    await sio.enter_room(sid, f"user:{user_id}")


@sio.event
async def disconnect(sid):
    user_id = _sid_user.pop(sid, None)
    if user_id is not None:
        _mark_online(user_id, sid, False)
        sids = _user_sids.get(user_id)
        if sids is not None:
            sids.discard(sid)
            if not sids:
                _user_sids.pop(user_id, None)


def _mark_online(user_id: str, sid: str, online: bool) -> None:
    """Best-effort: presence is a nicety, never a reason to drop a connection."""
    rc = _rc()
    if rc is None:
        return
    key = _ONLINE_KEY.format(user_id)
    try:
        if online:
            rc.sadd(key, sid)
            rc.expire(key, _ONLINE_TTL)
        else:
            rc.srem(key, sid)
    except Exception as exc:
        _log.warning("presence update failed for %s: %s", user_id, exc)


async def evict_from_group_room(user_id: UUID, group_id: UUID) -> None:
    """Remove every socket this user holds from a group's room.

    Call this whenever someone stops being an active member — leaving, being
    removed, or being frozen. The REST layer already refuses them, but the room
    membership is what decides who receives `new_group_message`,
    `new_group_deal` and the call events, and nothing else ever revokes it.

    A socket can only be removed by the worker that owns it, so this also
    broadcasts; every worker runs `_evict_local` for the sids it holds.
    """
    await _evict_local(user_id, group_id)
    rc = _rc()
    if rc is None:
        return
    try:
        rc.publish(_EVICT_CHANNEL, json.dumps(
            {"user_id": str(user_id), "group_id": str(group_id)}))
    except Exception as exc:
        _log.warning("evict broadcast failed for %s/%s: %s", user_id, group_id, exc)


async def _evict_local(user_id, group_id) -> None:
    """Leave the room for sids this worker owns. Best-effort: a socket that has
    already gone is not an error."""
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
    """True if the user holds a socket on ANY worker.

    Reads the shared Redis set; falls back to this process's rooms when Redis is
    unavailable, which is correct for a single worker and the best we can do.
    """
    rc = _rc()
    if rc is not None:
        try:
            return bool(rc.scard(_ONLINE_KEY.format(user_id)))
        except Exception as exc:
            _log.warning("presence lookup failed for %s, using local rooms: %s", user_id, exc)
    return bool(list(sio.manager.get_participants('/', f'user:{user_id}')))


def are_online(user_ids: list[UUID]) -> dict[UUID, bool]:
    """Batched is_online — one Redis round-trip (pipelined SCARD) for the whole
    list instead of one round-trip per user. Same fallback semantics as is_online."""
    if not user_ids:
        return {}
    rc = _rc()
    if rc is not None:
        try:
            pipe = rc.pipeline(transaction=False)
            for uid in user_ids:
                pipe.scard(_ONLINE_KEY.format(uid))
            counts = pipe.execute()
            return {uid: bool(c) for uid, c in zip(user_ids, counts)}
        except Exception as exc:
            _log.warning("batched presence lookup failed, using local rooms: %s", exc)
    return {uid: bool(list(sio.manager.get_participants('/', f'user:{uid}'))) for uid in user_ids}


async def start_evict_listener() -> None:
    """Subscribe this worker to eviction broadcasts. Called from the app lifespan."""
    global _evict_task
    if not _REDIS_URL or _evict_task is not None:
        return

    async def _listen() -> None:
        import redis.asyncio as aioredis

        while True:
            try:
                conn = aioredis.from_url(_REDIS_URL)
                pubsub = conn.pubsub()
                await pubsub.subscribe(_EVICT_CHANNEL)
                async for msg in pubsub.listen():
                    if msg.get("type") != "message":
                        continue
                    try:
                        data = json.loads(msg["data"])
                        await _evict_local(data["user_id"], data["group_id"])
                    except Exception as exc:
                        _log.warning("bad evict message: %s", exc)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _log.warning("evict listener dropped, retrying in 5s: %s", exc)
                await asyncio.sleep(5)

    _evict_task = asyncio.create_task(_listen())


async def stop_evict_listener() -> None:
    """Cancel the listener on shutdown, otherwise asyncio logs
    'Task was destroyed but it is pending!' on every restart."""
    global _evict_task
    task, _evict_task = _evict_task, None
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        _log.warning("evict listener shutdown: %s", exc)
