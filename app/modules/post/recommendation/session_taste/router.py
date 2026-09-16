"""
Post User Interaction endpoints.

POST /posts/interactions/batch               – submit a batch of interaction events
POST /posts/interactions/jobs/taste-update   – manually trigger the dwell taste update job
POST /posts/interactions/jobs/ignore-detect  – manually trigger the ignore detection job
"""
import redis
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.redis_client import get_redis
from app.dependencies import get_current_profile_id, get_current_user_id, get_db
from app.modules.post.recommendation.session_taste import service as interaction_service
from app.modules.post.recommendation.session_taste import jobs as interaction_jobs
from app.modules.post.recommendation.session_taste.schemas import (
    InteractionBatchPayload,
    InteractionBatchResult,
)
from app.modules.post.recommendation.schemas import JobResult

router = APIRouter(prefix="/posts/interactions", tags=["post-interactions"])

# See post/recommendation/router.py — job triggers are authenticated.
jobs_router = APIRouter(
    prefix="/posts/interactions/jobs",
    tags=["post-interactions"],
    dependencies=[Depends(get_current_user_id)],
)


@router.post("/batch", response_model=InteractionBatchResult)
def submit_interaction_batch(
    payload: InteractionBatchPayload,
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
    rc: redis.Redis = Depends(get_redis),
):
    """
    Accepts batched interaction events from the client:
    impression, dwell, open_read_more, open_carousel, open_comments, link_click.

    Dwell events with value_ms >= 3 000 ms automatically mark the post as seen
    (excluded from the recommendation feed for 30 days).

    Events older than 2 hours or referencing non-existent posts are silently
    dropped; the response reports accepted vs dropped counts.
    """
    result = interaction_service.process_interaction_batch(db, profile_id, payload.events, rc)
    return InteractionBatchResult(**result)


@jobs_router.post("/taste-update", response_model=JobResult)
def trigger_taste_update(db: Session = Depends(get_db)):
    """Manually trigger one batch of the dwell taste update job."""
    result = interaction_jobs.run_taste_update_job(db)
    return JobResult(status="ok", details=result)


@jobs_router.post("/ignore-detect", response_model=JobResult)
def trigger_ignore_detection(db: Session = Depends(get_db)):
    """Manually trigger the repeated-ignore detection job."""
    result = interaction_jobs.run_ignore_detection_job(db)
    return JobResult(status="ok", details=result)
