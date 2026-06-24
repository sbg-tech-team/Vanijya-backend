from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.dependencies import get_current_profile_id, get_current_user_id, get_db
from app.modules.news_new.news_user_interaction import service
from app.modules.news_new.news_user_interaction.schemas import (
    NewsInteractionBatchPayload,
    NewsInteractionBatchResult,
    NewsLikeOut,
    NewsSaveOut,
    NewsSendRequest,
    NewsSendResponse,
    NewsShareOut,
)
from app.shared.utils.response import ok

router = APIRouter(prefix="/news/interactions", tags=["News Interactions"])


@router.post("/batch")
def submit_interaction_batch(
    payload: NewsInteractionBatchPayload,
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    """
    Submit a batch of client-side interaction events (impression, dwell,
    open_article, share_tap). Events older than 2 hours or referencing
    unknown articles are silently dropped.
    """
    result = service.process_interaction_batch(db, profile_id, payload.events)
    return ok(result, "Batch processed")


@router.post("/like/{article_id}")
def toggle_like(
    article_id: UUID,
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    """Toggle like on an article. Returns the new like state."""
    is_liked = service.toggle_like(db, profile_id, article_id)
    return ok(NewsLikeOut(article_id=article_id, is_liked=is_liked).model_dump(mode="json"), "Like toggled")


@router.post("/save/{article_id}")
def toggle_save(
    article_id: UUID,
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    """Toggle save on an article. Returns the new save state."""
    is_saved = service.toggle_save(db, profile_id, article_id)
    return ok(NewsSaveOut(article_id=article_id, is_saved=is_saved).model_dump(mode="json"), "Save toggled")


@router.post("/share/{article_id}")
def record_share(
    article_id: UUID,
    platform: str | None = Query(None, description="Platform the user shared to (whatsapp, copy, etc.)"),
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    """
    External share only — increments share_count without delivering any in-app message.
    Use when the user shares via WhatsApp, copy link, or any channel outside the app.
    """
    service.record_share(db, profile_id, article_id, platform)
    return ok(NewsShareOut(article_id=article_id, platform=platform).model_dump(mode="json"), "Shared successfully")


@router.get("/share-sheet/{article_id}")
def get_news_share_recipients(
    article_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Called when the user taps Share on a news article.
    Returns DM connections and groups the user can forward the article to.
    Identical data shape as GET /connections/share-recipients.
    """
    from app.modules.chat.data.repository import ChatRepository
    result = ChatRepository(db).get_share_recipients(user_id)
    return ok(result, "Share recipients fetched")


@router.post("/send/{article_id}", response_model=NewsSendResponse)
async def send_news_article(
    article_id: UUID,
    payload: NewsSendRequest,
    background_tasks: BackgroundTasks,
    user_id: UUID = Depends(get_current_user_id),
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    """
    In-app news share: delivers the article as a 'news_article' chat message
    to selected DMs and groups, then increments share_count once.
    """
    from app.modules.chat.presentation.connection_manager import emit_to_user, emit_to_group
    try:
        result = service.send_article(db, article_id, user_id, profile_id, payload)
    except service.ArticleNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    for receiver_id, msg in result["dm_deliveries"]:
        background_tasks.add_task(emit_to_user, receiver_id, "new_message", jsonable_encoder(msg))
    for group_id, msg in result["group_deliveries"]:
        background_tasks.add_task(emit_to_group, group_id, "new_group_message", jsonable_encoder(msg))

    return NewsSendResponse(
        share_count=result["share_count"],
        delivered_to=len(result["dm_deliveries"]) + len(result["group_deliveries"]),
    )
