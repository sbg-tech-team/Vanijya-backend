"""
Feed routes — read-only endpoints for feed and article detail.

Paths match app_v1_backup/modules/news_new/feed/router.py exactly (the live
mobile client is built against these):

GET /news/feed              -> personalised recommended feed
GET /news/trending           -> platform-wide trending feed
GET /news/feed/saved        -> saved articles
GET /news/feed/global       -> geo_category == "global"
GET /news/feed/domestic     -> geo_category == "domestic"
GET /news/feed/government   -> is_government == True
GET /news/articles/{id}     -> full article detail
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.modules.news.application.use_cases.get_article_detail import GetArticleDetailUseCase
from app.modules.news.application.use_cases.get_feed import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    GetFeedUseCase,
)
from app.modules.news.domain.exceptions import ArticleNotFoundError
from app.modules.news.presentation.dependencies import (
    ProfileContextDep,
    RedisDep,
    get_article_detail_use_case,
    get_feed_use_case,
)
from app.modules.news.presentation.schemas import NewsCardDetailOut, NewsFeedPageOut
from app.shared.utils.response import ok

router = APIRouter(tags=["News Feed"])


def _feed_response(page, message: str):
    out = NewsFeedPageOut(articles=page.articles, next_cursor=page.next_cursor)
    return ok(out.model_dump(mode="json"), message)


@router.get("/feed")
def get_news_feed(
    profile: ProfileContextDep,
    use_case: Annotated[GetFeedUseCase, Depends(get_feed_use_case)],
    rc: RedisDep,
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor_article_id: str | None = Query(None),
):
    """Recommended feed for the landing page — time-bucketed, Layer 1 + Layer 2
    scored, session-taste amplified."""
    page = use_case.execute(
        profile_id=profile.profile_id,
        role_id=profile.role_id,
        commodity_interests=profile.commodity_interests,
        home_state=profile.home_state,
        feed_type="default",
        cursor_article_id=cursor_article_id,
        page_size=limit,
        rc=rc,
    )
    return _feed_response(page, "Feed fetched successfully")


@router.get("/trending")
def get_trending_feed(
    profile: ProfileContextDep,
    use_case: Annotated[GetFeedUseCase, Depends(get_feed_use_case)],
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor_article_id: str | None = Query(None),
):
    """Platform-wide trending articles ordered by velocity score."""
    page = use_case.execute(
        profile_id=profile.profile_id,
        role_id=profile.role_id,
        commodity_interests=profile.commodity_interests,
        home_state=profile.home_state,
        feed_type="trending",
        cursor_article_id=cursor_article_id,
        page_size=limit,
    )
    return _feed_response(page, "Trending news fetched")


@router.get("/feed/saved")
def get_saved_feed(
    profile: ProfileContextDep,
    use_case: Annotated[GetFeedUseCase, Depends(get_feed_use_case)],
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor_article_id: str | None = Query(None),
):
    """Articles the user has saved, most-recently-saved first."""
    page = use_case.execute(
        profile_id=profile.profile_id,
        role_id=profile.role_id,
        commodity_interests=profile.commodity_interests,
        home_state=profile.home_state,
        feed_type="saved",
        cursor_article_id=cursor_article_id,
        page_size=limit,
    )
    return _feed_response(page, "Saved articles fetched")


@router.get("/feed/global")
def get_global_feed(
    profile: ProfileContextDep,
    use_case: Annotated[GetFeedUseCase, Depends(get_feed_use_case)],
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor_article_id: str | None = Query(None),
):
    """Articles classified as global geo_category, ordered by recency."""
    page = use_case.execute(
        profile_id=profile.profile_id,
        role_id=profile.role_id,
        commodity_interests=profile.commodity_interests,
        home_state=profile.home_state,
        feed_type="global",
        cursor_article_id=cursor_article_id,
        page_size=limit,
    )
    return _feed_response(page, "Global feed fetched")


@router.get("/feed/domestic")
def get_domestic_feed(
    profile: ProfileContextDep,
    use_case: Annotated[GetFeedUseCase, Depends(get_feed_use_case)],
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor_article_id: str | None = Query(None),
):
    """Articles classified as domestic geo_category, ordered by recency."""
    page = use_case.execute(
        profile_id=profile.profile_id,
        role_id=profile.role_id,
        commodity_interests=profile.commodity_interests,
        home_state=profile.home_state,
        feed_type="domestic",
        cursor_article_id=cursor_article_id,
        page_size=limit,
    )
    return _feed_response(page, "Domestic feed fetched")


@router.get("/feed/government")
def get_government_feed(
    profile: ProfileContextDep,
    use_case: Annotated[GetFeedUseCase, Depends(get_feed_use_case)],
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor_article_id: str | None = Query(None),
):
    """Articles flagged is_government=True (any geo), ordered by recency."""
    page = use_case.execute(
        profile_id=profile.profile_id,
        role_id=profile.role_id,
        commodity_interests=profile.commodity_interests,
        home_state=profile.home_state,
        feed_type="government",
        cursor_article_id=cursor_article_id,
        page_size=limit,
    )
    return _feed_response(page, "Government feed fetched")


@router.get("/articles/{article_id}")
def get_article_detail(
    article_id: UUID,
    profile: ProfileContextDep,
    use_case: Annotated[GetArticleDetailUseCase, Depends(get_article_detail_use_case)],
):
    """Full article detail with stats and impact breakdown."""
    try:
        detail = use_case.execute(profile_id=profile.profile_id, article_id=article_id)
    except ArticleNotFoundError:
        raise HTTPException(status_code=404, detail="Article not found")
    out = NewsCardDetailOut.model_validate(detail)
    return ok(out.model_dump(mode="json"), "Article fetched")
