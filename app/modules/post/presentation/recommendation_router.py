"""
Post recommendation endpoints.

GET  /posts/recommendation/feed
POST /posts/recommendation/seen           ← deprecated no-op shim
POST /posts/recommendation/jobs/expiry
POST /posts/recommendation/jobs/popular-sync

Interaction events → POST /posts/interactions/batch  (post_user_interaction router)
"""
import redis
from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.redis_client import get_redis
from app.dependencies import get_current_profile_id, get_current_user_id
from app.modules.post.domain.interfaces.repository import IPostRepository
from app.modules.post.presentation.dependencies import get_post_repo
from app.modules.post.recommendation import service, jobs
from app.modules.post.presentation.recommendation_schemas import (
    FeedResponse,
    JobResult,
    PostSeenPayload,
)
from app.modules.post.recommendation.constants import FEED_SIZE

router = APIRouter(prefix="/posts/recommendation", tags=["post-recommendation"])

# The job triggers below duplicate work the scheduler already does, so an open
# endpoint is an unbounded write amplifier. Gated the same way /news/admin/* is.
jobs_router = APIRouter(
    prefix="/posts/recommendation/jobs",
    tags=["post-recommendation"],
    dependencies=[Depends(get_current_user_id)],
)


@router.get("/feed", response_model=FeedResponse)
def get_feed(
    profile_id: int = Depends(get_current_profile_id),
    repo: IPostRepository = Depends(get_post_repo),
    rc: redis.Redis = Depends(get_redis),
    limit: int = Query(default=FEED_SIZE, ge=1, le=50),
):
    try:
        posts = service.get_recommended_posts(repo, profile_id, limit=limit, rc=rc)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return FeedResponse(posts=posts, has_more=len(posts) >= limit)


@router.post("/seen", status_code=204)
def mark_seen(
    payload: PostSeenPayload,
    profile_id: int = Depends(get_current_profile_id),
):
    """
    Deprecated — use POST /posts/recommendation/interactions instead.
    Kept as a no-op shim for backward compatibility with older clients.
    """
    pass


@jobs_router.post("/expiry", response_model=JobResult)
def trigger_expiry_job(repo: IPostRepository = Depends(get_post_repo)):
    result = jobs.run_expiry_job(repo)
    return JobResult(status="ok", details=result)


@jobs_router.post("/popular-sync", response_model=JobResult)
def trigger_popular_sync(repo: IPostRepository = Depends(get_post_repo)):
    result = jobs.run_popular_posts_sync(repo)
    return JobResult(status="ok", details=result)
