"""
Post User Interaction endpoints.

POST /posts/interactions/batch               – submit a batch of interaction events
POST /posts/interactions/jobs/taste-update   – manually trigger the dwell taste update job
POST /posts/interactions/jobs/ignore-detect  – manually trigger the ignore detection job
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_current_profile_id, get_db
from app.modules.post.post_user_interaction import service as interaction_service
from app.modules.post.post_user_interaction import jobs as interaction_jobs
from app.modules.post.post_user_interaction.schemas import (
    InteractionBatchPayload,
    InteractionBatchResult,
)
from app.modules.post.post_recommendation_module.schemas import JobResult

router = APIRouter(prefix="/posts/interactions", tags=["post-interactions"])


@router.post("/batch", response_model=InteractionBatchResult)
def submit_interaction_batch(
    payload: InteractionBatchPayload,
    profile_id: int = Depends(get_current_profile_id),
    db: Session = Depends(get_db),
):
    """
    Accepts batched interaction events from the client:
    impression, dwell, open_read_more, open_carousel, open_comments, link_click.

    Dwell events with value_ms >= 3 000 ms automatically mark the post as seen
    (excluded from the recommendation feed for 30 days).

    Events older than 2 hours or referencing non-existent posts are silently
    dropped; the response reports accepted vs dropped counts.
    """
    result = interaction_service.process_interaction_batch(db, profile_id, payload.events)
    return InteractionBatchResult(**result)


@router.post("/jobs/taste-update", response_model=JobResult)
def trigger_taste_update(db: Session = Depends(get_db)):
    """Manually trigger one batch of the dwell taste update job."""
    result = interaction_jobs.run_taste_update_job(db)
    return JobResult(status="ok", details=result)


@router.post("/jobs/ignore-detect", response_model=JobResult)
def trigger_ignore_detection(db: Session = Depends(get_db)):
    """Manually trigger the repeated-ignore detection job."""
    result = interaction_jobs.run_ignore_detection_job(db)
    return JobResult(status="ok", details=result)
