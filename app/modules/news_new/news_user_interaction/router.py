from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_current_profile_id, get_db
from app.modules.news_new.news_user_interaction import service
from app.modules.news_new.news_user_interaction.schemas import (
    NewsInteractionBatchPayload,
    NewsInteractionBatchResult,
    NewsLikeOut,
    NewsSaveOut,
    NewsShareOut,
)

router = APIRouter(prefix="/news/interactions", tags=["News Interactions"])


@router.post("/batch", response_model=NewsInteractionBatchResult)
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
    return NewsInteractionBatchResult(**result)


@router.post("/like/{article_id}", response_model=NewsLikeOut)
def toggle_like(
    article_id: UUID,
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    """Toggle like on an article. Returns the new like state."""
    is_liked = service.toggle_like(db, profile_id, article_id)
    return NewsLikeOut(article_id=article_id, is_liked=is_liked)


@router.post("/save/{article_id}", response_model=NewsSaveOut)
def toggle_save(
    article_id: UUID,
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    """Toggle save on an article. Returns the new save state."""
    is_saved = service.toggle_save(db, profile_id, article_id)
    return NewsSaveOut(article_id=article_id, is_saved=is_saved)


@router.post("/share/{article_id}", response_model=NewsShareOut)
def record_share(
    article_id: UUID,
    platform: str | None = Query(None, description="Platform the user shared to (whatsapp, copy, etc.)"),
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    """Record a share event."""
    service.record_share(db, profile_id, article_id, platform)
    return NewsShareOut(article_id=article_id, platform=platform)
