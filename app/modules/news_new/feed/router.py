from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.dependencies import get_current_profile_id, get_db
from app.modules.news_new.feed import service as feed_service
from app.modules.news_new.feed.service import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.shared.utils.response import ok

router = APIRouter(prefix="/news", tags=["News Feed"])


@router.get("/feed")
def get_news_feed(
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor_article_id: str | None = Query(None),
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    """Recommended feed for the landing page — time-bucketed, Layer 1 + Layer 2 scored."""
    result = feed_service.get_recommended_feed(db, profile_id, limit, cursor_article_id)
    return ok(result.model_dump(mode="json"), "Feed fetched successfully")


@router.get("/trending")
def get_trending_feed(
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor_article_id: str | None = Query(None),
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    """Platform-wide trending articles ordered by velocity score."""
    result = feed_service.get_trending_news(db, profile_id, limit, cursor_article_id)
    return ok(result.model_dump(mode="json"), "Trending news fetched")


@router.get("/feed/saved")
def get_saved_feed(
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor_article_id: str | None = Query(None),
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    """Articles the user has saved, most-recently-saved first."""
    result = feed_service.get_saved_feed(db, profile_id, limit, cursor_article_id)
    return ok(result.model_dump(mode="json"), "Saved articles fetched")


@router.get("/feed/global")
def get_global_feed(
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor_article_id: str | None = Query(None),
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    """Articles classified as global geo_category, ordered by recency."""
    result = feed_service.get_filtered_feed(db, profile_id, "global", limit, cursor_article_id)
    return ok(result.model_dump(mode="json"), "Global feed fetched")


@router.get("/feed/domestic")
def get_domestic_feed(
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor_article_id: str | None = Query(None),
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    """Articles classified as domestic geo_category, ordered by recency."""
    result = feed_service.get_filtered_feed(db, profile_id, "domestic", limit, cursor_article_id)
    return ok(result.model_dump(mode="json"), "Domestic feed fetched")


@router.get("/feed/government")
def get_government_feed(
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor_article_id: str | None = Query(None),
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    """Articles flagged is_government=True (any geo), ordered by recency."""
    result = feed_service.get_filtered_feed(db, profile_id, "government", limit, cursor_article_id)
    return ok(result.model_dump(mode="json"), "Government feed fetched")


@router.get("/articles/{article_id}")
def get_article_detail(
    article_id: UUID,
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    """Full article detail with stats and impact breakdown."""
    result = feed_service.get_article_detail(db, article_id, profile_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return ok(result.model_dump(mode="json"), "Article fetched")
