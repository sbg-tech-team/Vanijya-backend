from uuid import UUID
import socketio
from app.core.database.session import SessionLocal
from app.core.security.jwt_handler import decode_access_token
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


async def emit_to_user(user_id: UUID, event: str, data: dict) -> None:
    await sio.emit(event, data, room=f"user:{user_id}")


async def emit_to_group(group_id: UUID, event: str, data: dict) -> None:
    await sio.emit(event, data, room=f"group:{group_id}")


def is_online(user_id: UUID) -> bool:
    return bool(list(sio.manager.get_participants('/', f'user:{user_id}')))
