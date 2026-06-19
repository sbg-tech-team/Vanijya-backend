"""
Home Feed Router

GET  /feed/home       — fetch a page of the home feed
POST /feed/engagement — submit engagement signals
"""
from __future__ import annotations

import json
from typing import Optional
from uuid import UUID

import redis

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.dependencies import CurrentUser, get_current_user, get_current_user_id, get_db
from app.core.redis_client import get_redis
from app.modules.feed.schemas import EngagementBatch, FeedCursor
from app.modules.feed.service import (
    ProfileNotFoundError,
    get_home_feed,
    submit_engagement,
)
from app.shared.utils.response import ok

router = APIRouter(prefix="/feed", tags=["Home Feed"])


@router.get("/home")
def home_feed(
    current: CurrentUser = Depends(get_current_user),
    cursor: Optional[str] = Query(None, description="JSON-encoded FeedCursor from previous page"),
    db: Session = Depends(get_db),
    r: redis.Redis = Depends(get_redis),
):
    """
    Returns a paginated, mixed home feed.

    - First call: omit `cursor` — breaking-news pins are prepended.
    - Subsequent calls: pass the `cursor` returned from the previous response.
    """
    parsed_cursor: Optional[FeedCursor] = None
    if cursor:
        try:
            parsed_cursor = FeedCursor(**json.loads(cursor))
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid cursor format")

    try:
        result = get_home_feed(
            db, current.user_id, current.profile_id, r, parsed_cursor
        )
    except ProfileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return ok(result.model_dump(), "Feed fetched successfully")


@router.post("/engagement", status_code=201)
def record_engagement(
    body: EngagementBatch,
    user_id: UUID = Depends(get_current_user_id),
):
    """
    Accepts a batch of engagement signals (dwell, like, save, skip, etc.).
    Acknowledged only for now — session taste processing re-enabled with Redis.
    """
    result = submit_engagement(user_id, body)
    return ok(result, "Engagement recorded")
