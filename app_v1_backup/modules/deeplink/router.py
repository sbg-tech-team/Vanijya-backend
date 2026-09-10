from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.modules.deeplink import service
from app.modules.deeplink.schemas import ShareLinkResponse
from app.shared.utils.response import ok

router = APIRouter(prefix="/share", tags=["Deep Links"])


@router.get("/post/{post_id}", response_model=None)
def share_post(
    post_id: int,
    db: Session = Depends(get_db),
):
    """Return a vanijyaa://post/{id} deep link + ready-to-send share text."""
    try:
        result = service.get_post_share_link(db, post_id)
    except service.DeepLinkNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ok(ShareLinkResponse(**result), "Share link generated")


@router.get("/news/{article_id}", response_model=None)
def share_news(
    article_id: str,
    db: Session = Depends(get_db),
):
    """Return a vanijyaa://news/{uuid} deep link + ready-to-send share text."""
    try:
        result = service.get_news_share_link(db, article_id)
    except service.DeepLinkNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ok(ShareLinkResponse(**result), "Share link generated")


@router.get("/user/{profile_id}", response_model=None)
def share_user(
    profile_id: int,
    db: Session = Depends(get_db),
):
    """Return a vanijyaa://user/{id} deep link + ready-to-send share text."""
    try:
        result = service.get_user_share_link(db, profile_id)
    except service.DeepLinkNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ok(ShareLinkResponse(**result), "Share link generated")
