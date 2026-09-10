from fastapi import APIRouter, Depends, HTTPException

from app.modules.deeplink.application import service
from app.modules.deeplink.domain.exceptions import DeepLinkNotFoundError
from app.modules.deeplink.domain.interfaces.repository import IDeepLinkRepository
from app.modules.deeplink.presentation.dependencies import get_deeplink_repo
from app.modules.deeplink.presentation.schemas import ShareLinkResponse
from app.shared.utils.response import ok

router = APIRouter(prefix="/share", tags=["Deep Links"])


@router.get("/post/{post_id}", response_model=None)
def share_post(
    post_id: int,
    repo: IDeepLinkRepository = Depends(get_deeplink_repo),
):
    """Return a vanijyaa://post/{id} deep link + ready-to-send share text."""
    try:
        result = service.get_post_share_link(repo, post_id)
    except DeepLinkNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ok(ShareLinkResponse(**result), "Share link generated")


@router.get("/news/{article_id}", response_model=None)
def share_news(
    article_id: str,
    repo: IDeepLinkRepository = Depends(get_deeplink_repo),
):
    """Return a vanijyaa://news/{uuid} deep link + ready-to-send share text."""
    try:
        result = service.get_news_share_link(repo, article_id)
    except DeepLinkNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ok(ShareLinkResponse(**result), "Share link generated")


@router.get("/user/{profile_id}", response_model=None)
def share_user(
    profile_id: int,
    repo: IDeepLinkRepository = Depends(get_deeplink_repo),
):
    """Return a vanijyaa://user/{id} deep link + ready-to-send share text."""
    try:
        result = service.get_user_share_link(repo, profile_id)
    except DeepLinkNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ok(ShareLinkResponse(**result), "Share link generated")
