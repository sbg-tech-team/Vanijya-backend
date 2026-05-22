from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from app.modules.chat.domain.entities import ConvStatus, ConversationEntity, LastMessage, MessageEntity, UserSnap
from app.modules.chat.domain.use_cases import (
    AcceptConversationUseCase,
    DeclineConversationUseCase,
    GetConversationsUseCase,
    GetGroupMessagesUseCase,
    GetMessagesUseCase,
    MarkReadUseCase,
    OpenChatUseCase,
    SendGroupMessageUseCase,
)
from app.modules.chat.presentation.connection_manager import manager
from app.modules.chat.presentation.dependencies import (
    get_accept_uc,
    get_chat_repo,
    get_conversations_uc,
    get_decline_uc,
    get_group_message_uc,
    get_group_messages_uc,
    get_mark_read_uc,
    get_messages_uc,
    get_open_chat_uc,
)
from app.modules.chat.domain.repository import IChatRepository
from app.modules.chat.presentation.schemas import GroupMessageRequest, OpenChatRequest, SendMessageRequest
from app.shared.utils.response import ok

router = APIRouter(prefix="/api/v1/chat", tags=["Chat"])


def _snap(u: UserSnap) -> dict:
    return {"user_id": str(u.user_id), "profile_id": u.profile_id, "name": u.name, "is_user_verified": u.is_user_verified, "is_business_verified": u.is_business_verified}


def _last_msg(lm: Optional[LastMessage]) -> Optional[dict]:
    if lm is None:
        return None
    return {"id": str(lm.id), "body": lm.body, "message_type": lm.message_type, "sender_id": str(lm.sender_id), "sent_at": lm.sent_at.isoformat()}


def _conv(c: ConversationEntity) -> dict:
    return {
        "id": str(c.id),
        "status": c.status,
        "participant": _snap(c.participant),
        "last_message": _last_msg(c.last_message),
        "unread_count": c.unread_count,
        "is_muted": c.is_muted,
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat(),
    }


def _msg(m: MessageEntity) -> dict:
    return {
        "id": str(m.id),
        "context_id": str(m.context_id),
        "context_type": m.context_type,
        "sender": _snap(m.sender),
        "message_type": m.message_type,
        "body": m.body,
        "media_url": m.media_url,
        "media_metadata": m.media_metadata,
        "location_lat": m.location_lat,
        "location_lon": m.location_lon,
        "reply_to_id": str(m.reply_to_id) if m.reply_to_id else None,
        "is_deleted": m.is_deleted,
        "sent_at": m.sent_at.isoformat(),
    }


@router.get("/{user_id}/conversations")
def list_conversations(
    user_id: UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    uc: GetConversationsUseCase = Depends(get_conversations_uc),
):
    convs = uc.execute(user_id, page, per_page)
    return ok({"conversations": [_conv(c) for c in convs], "page": page, "per_page": per_page}, "Conversations fetched")


@router.post("/{user_id}/conversations", status_code=201)
def open_chat(
    user_id: UUID,
    payload: OpenChatRequest,
    background_tasks: BackgroundTasks,
    uc: OpenChatUseCase = Depends(get_open_chat_uc),
):
    conv, message, created = uc.execute(user_id, payload.participant_id, payload.message)
    msg_dict = _msg(message)
    background_tasks.add_task(
        manager.push,
        payload.participant_id,
        {"event": "new_message", "data": {"conversation_id": str(conv.id), "message": msg_dict}},
    )
    return ok({"conversation": _conv(conv), "message": msg_dict, "created": created}, "Chat opened" if created else "Existing chat returned")


@router.get("/{user_id}/conversations/{conv_id}/messages")
def get_messages(
    user_id: UUID,
    conv_id: UUID,
    before: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    uc: GetMessagesUseCase = Depends(get_messages_uc),
):
    messages = uc.execute(user_id, conv_id, before, limit)
    return ok(
        {
            "messages": [_msg(m) for m in messages],
            "has_more": len(messages) == limit,
            "oldest_timestamp": messages[-1].sent_at.isoformat() if messages else None,
        },
        "Messages fetched",
    )


@router.post("/{user_id}/conversations/{conv_id}/messages", status_code=201)
async def send_message(
    user_id: UUID,
    conv_id: UUID,
    payload: SendMessageRequest,
    background_tasks: BackgroundTasks,
    repo: IChatRepository = Depends(get_chat_repo),
):
    # 1 query: membership check + status + receiver_id + sender profile
    guard = repo.get_conv_send_info(conv_id, user_id)
    if guard is None:
        raise HTTPException(status_code=404, detail="Conversation not found or you are not a member.")
    if guard.status == ConvStatus.BLOCKED:
        raise HTTPException(status_code=403, detail="This conversation is blocked.")
    if guard.status == ConvStatus.REQUESTED and (guard.initiator_id is None or user_id != guard.initiator_id):
        raise HTTPException(status_code=403, detail="Waiting for the other person to accept the chat request.")

    # Build message in memory — no DB needed
    msg_id  = uuid4()
    sent_at = datetime.now(timezone.utc)
    msg_dict = {
        "id":             str(msg_id),
        "context_id":     str(conv_id),
        "context_type":   "dm",
        "sender":         _snap(guard.sender_snap),
        "message_type":   payload.message_type,
        "body":           payload.body,
        "media_url":      payload.media_url,
        "media_metadata": payload.media_metadata,
        "location_lat":   payload.location_lat,
        "location_lon":   payload.location_lon,
        "reply_to_id":    str(payload.reply_to_id) if payload.reply_to_id else None,
        "is_deleted":     False,
        "sent_at":        sent_at.isoformat(),
    }

    # Push to receiver IMMEDIATELY — before any DB write
    await manager.push(
        guard.receiver_id,
        {"event": "new_message", "data": {"conversation_id": str(conv_id), "message": msg_dict}},
    )

    # Persist to DB in background — own session, non-blocking
    background_tasks.add_task(
        repo.persist_message,
        msg_id, sent_at, "dm", conv_id, user_id,
        payload.body, payload.message_type,
        payload.media_url, payload.media_metadata,
        payload.location_lat, payload.location_lon,
        payload.reply_to_id,
    )

    return ok({"message": msg_dict}, "Message sent")


@router.post("/{user_id}/conversations/{conv_id}/accept")
def accept_conversation(
    user_id: UUID,
    conv_id: UUID,
    uc: AcceptConversationUseCase = Depends(get_accept_uc),
):
    conv = uc.execute(user_id, conv_id)
    return ok({"conversation": _conv(conv)}, "Chat request accepted")


@router.post("/{user_id}/conversations/{conv_id}/decline")
def decline_conversation(
    user_id: UUID,
    conv_id: UUID,
    uc: DeclineConversationUseCase = Depends(get_decline_uc),
):
    conv = uc.execute(user_id, conv_id)
    return ok({"conversation": _conv(conv)}, "Chat request declined")


@router.post("/{user_id}/conversations/{conv_id}/read")
def mark_read(
    user_id: UUID,
    conv_id: UUID,
    uc: MarkReadUseCase = Depends(get_mark_read_uc),
):
    uc.execute(user_id, conv_id)
    return ok(None, "Marked as read")


@router.get("/{user_id}/groups/{group_id}/messages")
def get_group_messages(
    user_id: UUID,
    group_id: UUID,
    before: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    uc: GetGroupMessagesUseCase = Depends(get_group_messages_uc),
):
    messages = uc.execute(user_id, group_id, before, limit)
    return ok(
        {
            "messages": [_msg(m) for m in messages],
            "has_more": len(messages) == limit,
            "oldest_timestamp": messages[-1].sent_at.isoformat() if messages else None,
        },
        "Group messages fetched",
    )


@router.post("/{user_id}/groups/{group_id}/messages", status_code=201)
def send_group_message(
    user_id: UUID,
    group_id: UUID,
    payload: GroupMessageRequest,
    background_tasks: BackgroundTasks,
    uc: SendGroupMessageUseCase = Depends(get_group_message_uc),
):
    message, member_ids = uc.execute(
        sender_id=user_id,
        group_id=group_id,
        body=payload.body,
        message_type=payload.message_type,
        media_url=payload.media_url,
        media_metadata=payload.media_metadata,
        reply_to_id=payload.reply_to_id,
    )
    msg_dict = _msg(message)
    # Push to all online group members except the sender
    recipients = [uid for uid in member_ids if uid != user_id]
    background_tasks.add_task(
        manager.push_to_many,
        recipients,
        {"event": "new_group_message", "data": {"group_id": str(group_id), "message": msg_dict}},
    )
    return ok({"message": msg_dict}, "Group message sent")
