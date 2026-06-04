"""
Post recommendation endpoints.

GET  /posts/recommendation/feed
POST /posts/recommendation/seen
POST /posts/recommendation/jobs/expiry
POST /posts/recommendation/jobs/popular-sync
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.dependencies import get_current_profile_id, get_db
from app.modules.post.post_recommendation_module import service, jobs
from app.modules.post.post_recommendation_module.schemas import (
    FeedResponse,
    JobResult,
    PostSeenPayload,
)
from app.modules.post.post_recommendation_module.constants import FEED_SIZE

router = APIRouter(prefix="/posts/recommendation", tags=["post-recommendation"])


@router.get("/feed", response_model=FeedResponse)
def get_feed(
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
    limit: int = Query(default=FEED_SIZE, ge=1, le=50),
):
    try:
        posts = service.get_recommended_posts(db, profile_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return FeedResponse(posts=posts, has_more=len(posts) >= limit)


@router.post("/seen", status_code=204)
def mark_seen(
    payload: PostSeenPayload,
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    """
    Mark posts as seen. Frontend decides when a post qualifies as seen
    (dwell time, scroll-past, explicit open). Excluded from recommendation
    feed for 30 days from first call.
    """
    service.record_seen(db, profile_id, payload.post_ids)


@router.post("/jobs/expiry", response_model=JobResult)
def trigger_expiry_job(db: Session = Depends(get_db)):
    result = jobs.run_expiry_job(db)
    return JobResult(status="ok", details=result)


@router.post("/jobs/popular-sync", response_model=JobResult)
def trigger_popular_sync(db: Session = Depends(get_db)):
    result = jobs.run_popular_posts_sync(db)
    return JobResult(status="ok", details=result)
