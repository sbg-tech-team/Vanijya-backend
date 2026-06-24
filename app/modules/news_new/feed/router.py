from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_current_profile_id, get_db
from app.modules.news_new.feed import service as feed_service
from app.modules.news_new.feed.service import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.modules.profile.models import Profile
from app.shared.utils.response import ok

router = APIRouter(prefix="/news", tags=["News Feed"])


def _get_role_id(profile_id: int, db: Session) -> int | None:
    profile = db.execute(
        select(Profile).where(Profile.id == profile_id)
    ).scalar_one_or_none()
    return profile.role_id if profile else None


@router.get("/feed")
def get_news_feed(
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(None, description="Pagination cursor from previous response"),
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    """Reverse-chronological feed of enriched articles, role-scored."""
    role_id = _get_role_id(profile_id, db)
    result = feed_service.get_trending_feed(db, profile_id, role_id, limit, cursor)
    return ok(result.model_dump(mode="json"), "Feed fetched successfully")


@router.get("/feed/saved")
def get_saved_feed(
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(None),
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    """Articles the user has saved, most-recently-saved first."""
    role_id = _get_role_id(profile_id, db)
    result = feed_service.get_saved_feed(db, profile_id, role_id, limit, cursor)
    return ok(result.model_dump(mode="json"), "Saved articles fetched")


@router.get("/feed/global")
def get_global_feed(
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(None),
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    """Articles classified as global geo_category."""
    role_id = _get_role_id(profile_id, db)
    result = feed_service.get_filtered_feed(db, profile_id, "global", role_id, limit, cursor)
    return ok(result.model_dump(mode="json"), "Global feed fetched")


@router.get("/feed/domestic")
def get_domestic_feed(
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(None),
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    """Articles classified as domestic geo_category."""
    role_id = _get_role_id(profile_id, db)
    result = feed_service.get_filtered_feed(db, profile_id, "domestic", role_id, limit, cursor)
    return ok(result.model_dump(mode="json"), "Domestic feed fetched")


@router.get("/feed/government")
def get_government_feed(
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(None),
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    """Articles flagged is_government=True (government/regulator/policy, any geo)."""
    role_id = _get_role_id(profile_id, db)
    result = feed_service.get_filtered_feed(db, profile_id, "government", role_id, limit, cursor)
    return ok(result.model_dump(mode="json"), "Government feed fetched")


@router.get("/articles/{article_id}")
def get_article_detail(
    article_id: UUID,
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    """Full article detail card with stats, impact explanation, and factor breakdown."""
    role_id = _get_role_id(profile_id, db)
    result = feed_service.get_article_detail(db, article_id, profile_id, role_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return ok(result.model_dump(mode="json"), "Article fetched")
