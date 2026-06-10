from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.dependencies import get_current_user_id, get_db
from app.modules.chat import service as chat_service
from app.modules.chat.data.repository import ChatRepository
from app.modules.chat.domain.entities import ConvStatus
from app.modules.chat.presentation.connection_manager import emit_to_group, emit_to_user
from app.modules.chat.presentation.dependencies import (
    get_accept_uc,
    get_chat_repo,
    get_conversations_uc,
    get_decline_uc,
    get_delete_message_uc,
    get_group_message_uc,
    get_group_messages_uc,
    get_mark_read_uc,
    get_messages_uc,
    get_open_chat_uc,
    get_personal_deal_uc,
)
from app.modules.chat.presentation.schema import (
    CreatePersonalDealRequest,
    OpenChatRequest,
    SendGroupMessageRequest,
    SendMessageRequest,
)
from app.modules.groups.schemas import GroupDealCreate
from app.modules.groups.service import GroupPermissionError, create_group_deal

router = APIRouter(prefix="/chat", tags=["chat"])


# ── DM Conversations ──────────────────────────────────────────────────────────

@router.get("/conversations")
def list_conversations(
    page: int = 1,
    per_page: int = 20,
    user_id: UUID = Depends(get_current_user_id),
    uc=Depends(get_conversations_uc),
):
    return uc.execute(user_id, page, per_page)


@router.post("/conversations", status_code=201)
async def open_chat(
    body: OpenChatRequest,
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id),
    uc=Depends(get_open_chat_uc),
):
    conv, msg, created = uc.execute(
        sender_id=user_id,
        participant_id=body.participant_id,
        first_message=body.first_message,
    )
    background_tasks.add_task(emit_to_user, body.participant_id, "new_message", jsonable_encoder(msg))
    return {"conversation": conv, "message": msg, "created": created}


@router.get("/conversations/{conv_id}/messages")
def get_messages(
    conv_id: UUID,
    before: Optional[datetime] = None,
    limit: int = 50,
    user_id: UUID = Depends(get_current_user_id),
    uc=Depends(get_messages_uc),
):
    return uc.execute(user_id, conv_id, before, limit)


@router.post("/conversations/{conv_id}/messages", status_code=201)
async def send_message(
    conv_id: UUID,
    body: SendMessageRequest,
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id),
    repo: ChatRepository = Depends(get_chat_repo),
):
    guard = repo.get_conv_send_info(conv_id, user_id)
    if not guard:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    if guard.status == ConvStatus.BLOCKED:
        raise HTTPException(status_code=403, detail="Blocked conversation.")
    if guard.status == ConvStatus.REQUESTED and (
        guard.initiator_id is None or user_id != guard.initiator_id
    ):
        raise HTTPException(status_code=403, detail="Waiting for the other person to accept.")

    msg = repo.save_message(
        context_type="dm",
        context_id=conv_id,
        sender_id=user_id,
        body=body.body,
        message_type=body.message_type,
        media_urls=body.media_urls,
        media_metadata=body.media_metadata,
        location_lat=body.location_lat,
        location_lon=body.location_lon,
        reply_to_id=body.reply_to_id,
        deal_id=body.deal_id,
        personal_deal_id=body.personal_deal_id,
        post_id=body.post_id,
    )
    background_tasks.add_task(emit_to_user, guard.receiver_id, "new_message", jsonable_encoder(msg))
    return msg


@router.post("/conversations/{conv_id}/read")
async def mark_read(
    conv_id: UUID,
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id),
    uc=Depends(get_mark_read_uc),
    repo: ChatRepository = Depends(get_chat_repo),
):
    uc.execute(user_id, conv_id)
    guard = repo.get_conv_send_info(conv_id, user_id)
    if guard:
        background_tasks.add_task(
            emit_to_user,
            guard.receiver_id,
            "read",
            {"conv_id": str(conv_id), "reader_id": str(user_id)},
        )
    return {"ok": True}


@router.post("/conversations/{conv_id}/accept")
async def accept_conversation(
    conv_id: UUID,
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id),
    uc=Depends(get_accept_uc),
):
    conv = uc.execute(user_id, conv_id)
    if conv.initiator_id:
        background_tasks.add_task(emit_to_user, conv.initiator_id, "conversation_accepted", {"conv_id": str(conv_id)})
    return conv


@router.post("/conversations/{conv_id}/decline")
async def decline_conversation(
    conv_id: UUID,
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id),
    uc=Depends(get_decline_uc),
):
    conv = uc.execute(user_id, conv_id)
    if conv.initiator_id:
        background_tasks.add_task(emit_to_user, conv.initiator_id, "conversation_declined", {"conv_id": str(conv_id)})
    return conv


@router.post("/conversations/{conv_id}/deals", status_code=201)
async def create_personal_deal(
    conv_id: UUID,
    body: CreatePersonalDealRequest,
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id),
    uc=Depends(get_personal_deal_uc),
    repo: ChatRepository = Depends(get_chat_repo),
):
    msg = uc.execute(
        sender_id=user_id,
        conv_id=conv_id,
        commodity_id=body.commodity_id,
        title=body.title,
        caption=body.caption,
        grain_type=body.grain_type,
        grain_size=body.grain_size,
        commodity_quantity=body.commodity_quantity,
        quantity_unit=body.quantity_unit,
        commodity_price=body.commodity_price,
        price_type=body.price_type,
        image_urls=body.image_urls,
    )
    guard = repo.get_conv_send_info(conv_id, user_id)
    if guard:
        background_tasks.add_task(emit_to_user, guard.receiver_id, "new_message", jsonable_encoder(msg))
    return msg


# ── Media upload ──────────────────────────────────────────────────────────────

@router.post("/media/upload-url", status_code=201)
async def get_chat_media_upload_url(
    content_type: str = Query(..., description="image/* | video/* | audio/* | application/pdf"),
    user_id: UUID = Depends(get_current_user_id),
):
    """
    Step 1 of 3 — get a signed upload URL for a chat attachment.
    Step 2: PUT the bytes directly to upload_url (Content-Type must match).
    Step 3: send the message with the returned media_url in media_urls.
    """
    try:
        return await chat_service.get_chat_media_upload_url(user_id, content_type)
    except chat_service.ChatMediaUploadError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except chat_service.ChatStorageUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))


# ── Delete message ────────────────────────────────────────────────────────────

@router.delete("/messages/{message_id}")
async def delete_message(
    message_id: UUID,
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id),
    uc=Depends(get_delete_message_uc),
    repo: ChatRepository = Depends(get_chat_repo),
):
    info = uc.execute(user_id, message_id)

    event = {"message_id": str(message_id), "context_id": str(info["context_id"])}
    if info["context_type"] == "group":
        background_tasks.add_task(emit_to_group, info["context_id"], "message_deleted", event)
    else:
        guard = repo.get_conv_send_info(info["context_id"], user_id)
        if guard:
            background_tasks.add_task(emit_to_user, guard.receiver_id, "message_deleted", event)

    if info["storage_paths"]:
        background_tasks.add_task(chat_service.delete_chat_media, info["storage_paths"])

    return {"ok": True, "message_id": str(message_id)}


# ── Group Chat ────────────────────────────────────────────────────────────────

@router.get("/groups/{group_id}/messages")
def get_group_messages(
    group_id: UUID,
    before: Optional[datetime] = None,
    limit: int = 50,
    user_id: UUID = Depends(get_current_user_id),
    uc=Depends(get_group_messages_uc),
):
    return uc.execute(user_id, group_id, before, limit)


@router.post("/groups/{group_id}/messages", status_code=201)
async def send_group_message(
    group_id: UUID,
    body: SendGroupMessageRequest,
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id),
    uc=Depends(get_group_message_uc),
):
    msg = uc.execute(
        sender_id=user_id,
        group_id=group_id,
        body=body.body,
        message_type=body.message_type,
        media_urls=body.media_urls,
        media_metadata=body.media_metadata,
        location_lat=body.location_lat,
        location_lon=body.location_lon,
        reply_to_id=body.reply_to_id,
        deal_id=body.deal_id,
        post_id=body.post_id,
    )
    background_tasks.add_task(emit_to_group, group_id, "new_group_message", jsonable_encoder(msg))
    return msg


@router.post("/groups/{group_id}/deals", status_code=201)
async def create_group_deal_endpoint(
    group_id: UUID,
    payload: GroupDealCreate,
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        deal = create_group_deal(db, group_id, user_id, payload)
    except GroupPermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    background_tasks.add_task(emit_to_group, group_id, "new_group_deal", jsonable_encoder(deal))
    return deal
