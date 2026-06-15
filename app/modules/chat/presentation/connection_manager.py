"""Socket.IO server + emit helpers for chat real-time push.

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
from uuid import UUID
import socketio
from app.core.database.session import SessionLocal
from app.core.security.jwt_handler import decode_access_token
from app.modules.chat.data.models import ConversationMember
from app.modules.groups.models import GroupMember

sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')

# sid → str(user_id) — needed to verify group membership in join_group
_sid_user: dict[str, str] = {}


@sio.event
async def connect(sid, _environ, auth):
    try:
        token = auth.get("token")
        decoded_token = decode_access_token(token)
    except Exception:
        return False
    user_id = str(decoded_token.user_id)
    _sid_user[sid] = user_id
    await sio.enter_room(sid, f"user:{user_id}")


@sio.event
async def disconnect(sid):
    _sid_user.pop(sid, None)


@sio.event
async def join_group(sid, data):
    group_id = data.get("group_id")
    user_id = _sid_user.get(sid)
    if not group_id or not user_id:
        return

    db = SessionLocal()
    try:
        member = db.query(GroupMember).filter(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user_id,
        ).first()
    finally:
        db.close()

    if member is None:
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
    user_id = _sid_user.get(sid)
    context_type = (data or {}).get("context_type")
    context_id = (data or {}).get("context_id")
    if not user_id or not context_type or not context_id:
        return

    payload = {"context_type": context_type, "context_id": str(context_id), "user_id": user_id}

    if context_type == "group":
        await sio.emit(event, payload, room=f"group:{context_id}", skip_sid=sid)
        return

    if context_type == "dm":
        db = SessionLocal()
        try:
            rows = (
                db.query(ConversationMember.user_id)
                .filter(ConversationMember.conversation_id == context_id)
                .all()
            )
        finally:
            db.close()
        member_ids = [str(r[0]) for r in rows]
        if user_id not in member_ids:
            return  # not a member — refuse to relay
        for mid in member_ids:
            if mid != user_id:
                await sio.emit(event, payload, room=f"user:{mid}")


async def emit_to_user(user_id: UUID, event: str, data: dict) -> None:
    await sio.emit(event, data, room=f"user:{user_id}")


async def emit_to_group(group_id: UUID, event: str, data: dict) -> None:
    await sio.emit(event, data, room=f"group:{group_id}")


def is_online(user_id: UUID) -> bool:
    return bool(list(sio.manager.get_participants('/', f'user:{user_id}')))
