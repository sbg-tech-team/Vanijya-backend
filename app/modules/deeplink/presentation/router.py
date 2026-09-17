import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.rate_limiter import RateLimiter
from app.core.redis_client import get_redis
from app.modules.deeplink.application import service
from app.modules.deeplink.domain.exceptions import DeepLinkNotFoundError
from app.modules.deeplink.domain.interfaces.repository import IDeepLinkRepository
from app.modules.deeplink.presentation.dependencies import get_deeplink_repo
from app.modules.deeplink.presentation.schemas import ShareLinkResponse
from app.shared.utils.response import ok

log = logging.getLogger(__name__)

# These three are the only unauthenticated reads in the app — a share link has to
# open for someone with no account. But profile_id is sequential, so without a
# limit anyone can walk 1,2,3... and harvest every user's name, company and city.
# Throttling per IP keeps real share opens working and makes bulk scraping slow.
_limiter = RateLimiter()
_SHARE_LIMIT, _SHARE_WINDOW = 60, 60


def share_throttle(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    try:
        _limiter.check(get_redis(), f"share:{ip}", limit=_SHARE_LIMIT, window=_SHARE_WINDOW)
    except HTTPException:
        raise                       # 429
    except Exception as exc:
        # A Redis outage must not break sharing.
        log.warning("share rate limiting unavailable: %s", exc)


router = APIRouter(
    prefix="/share", tags=["Deep Links"], dependencies=[Depends(share_throttle)],
)


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
