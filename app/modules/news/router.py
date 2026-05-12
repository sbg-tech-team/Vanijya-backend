from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.dependencies import get_current_user_id, get_db
from app.modules.news.schemas import (
    CommentRequest,
    EngageRequest,
)
from app.modules.news.service import (
    NewsNotFoundError,
    NewsValidationError,
    ProfileNotFoundError,
    get_article,
    get_comments,
    get_engagement_history,
    get_news_feed,
    get_saved_articles,
    get_taste_profile,
    post_comment,
    record_engagement,
    search_news,
    share_article,
    toggle_like,
    toggle_save,
)
from app.shared.utils.response import ok

router = APIRouter(prefix="/news", tags=["News"])


# ── Feed ──────────────────────────────────────────────────────────────────────

@router.get("/feed")
def news_feed(
    user_id: UUID = Depends(get_current_user_id),
    state: str = Query("", description="User's state e.g. punjab (optional)"),
    scope: str = Query("national", description="local | state | national | global"),
    db: Session = Depends(get_db),
):
    try:
        result = get_news_feed(db, user_id, state.lower(), scope)
        return ok(result.model_dump(), "Feed fetched successfully")
    except ProfileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Search ────────────────────────────────────────────────────────────────────

@router.get("/search")
def search(
    q: str = Query("", description="Search query"),
    commodity: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    results = search_news(db, q, commodity, page, per_page)
    return ok([r.model_dump() for r in results], "Search results")


# ── Taste profile ─────────────────────────────────────────────────────────────

@router.get("/my/taste")
def my_taste(
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        result = get_taste_profile(db, user_id)
        return ok(result.model_dump(), "Taste profile fetched")
    except ProfileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Engagement history ────────────────────────────────────────────────────────

@router.get("/my/history")
def my_history(
    user_id: UUID = Depends(get_current_user_id),
    action_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    results = get_engagement_history(db, user_id, action_type, page, per_page)
    return ok([r.model_dump() for r in results], "Engagement history fetched")


# ── Saved articles ───────────────────────────────────────────────────────────

@router.get("/saved")
def saved_articles(
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    results = get_saved_articles(db, user_id)
    return ok([r.model_dump() for r in results], "Saved articles fetched")


# ── Single article ────────────────────────────────────────────────────────────

@router.get("/{article_id}")
def article_detail(
    article_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        result = get_article(db, article_id, user_id)
        return ok(result.model_dump(), "Article fetched")
    except NewsNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Engage ────────────────────────────────────────────────────────────────────

@router.post("/{article_id}/engage", status_code=201)
def engage(
    article_id: UUID,
    payload: EngageRequest,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        record_engagement(
            db,
            user_id,
            article_id,
            payload.action_type,
            payload.dwell_time_s,
            payload.comment_text,
            payload.segment_id,
        )
        return ok(message="Engagement recorded")
    except NewsNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except NewsValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Like ──────────────────────────────────────────────────────────────────────

@router.post("/{article_id}/like")
def like(
    article_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        result = toggle_like(db, user_id, article_id)
        return ok(result.model_dump(), "Like toggled")
    except NewsNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Save ──────────────────────────────────────────────────────────────────────

@router.post("/{article_id}/save")
def save(
    article_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        result = toggle_save(db, user_id, article_id)
        return ok(result.model_dump(), "Save toggled")
    except NewsNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Share ─────────────────────────────────────────────────────────────────────

@router.post("/{article_id}/share")
def share(
    article_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        result = share_article(db, user_id, article_id)
        return ok(result.model_dump(), "Shared successfully")
    except NewsNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Comment ───────────────────────────────────────────────────────────────────

@router.post("/{article_id}/comment", status_code=201)
def comment(
    article_id: UUID,
    payload: CommentRequest,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        post_comment(db, user_id, article_id, payload.text)
        return ok(message="Comment posted")
    except NewsNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{article_id}/comments")
def comments(
    article_id: UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    results = get_comments(db, article_id, page, per_page)
    return ok([r.model_dump() for r in results], "Comments fetched")
