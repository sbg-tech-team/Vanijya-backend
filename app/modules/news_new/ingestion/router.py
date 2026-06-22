from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_current_user_id, get_db
from app.modules.news_new.config import (
    ENRICH_BATCH_LIMIT,
    GNEWS_DEFAULT_COUNTRY,
)
from app.modules.news_new.ingestion.providers.gnews import GNewsProvider
from app.modules.news_new.ingestion.service import (
    get_stats,
    ingest_from_provider,
    ingest_rotation,
)
from app.modules.news_new.intelligence.service import enrich_pending
from app.shared.utils.response import ok

router = APIRouter(prefix="/news/admin", tags=["News Ingestion"])


@router.post("/ingest")
def trigger_ingest(
    query: str | None = Query(None, description="GNews query. Omit to run the rotation pool batch."),
    country: str | None = Query(GNEWS_DEFAULT_COUNTRY, description="ISO country bias (single-query mode); blank for global"),
    _user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Ingest new raw articles (status=pending). With `query` → single query;
    without → the rotating batch of platform queries (same as the scheduled run).
    """
    if query:
        result = ingest_from_provider(db, GNewsProvider(), query, country=country or None)
    else:
        result = ingest_rotation(db, GNewsProvider())
    return ok(result, "Ingestion complete")


@router.post("/enrich")
def trigger_enrich(
    limit: int = Query(ENRICH_BATCH_LIMIT, ge=1, le=100, description="Max pending to enrich"),
    _user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Enrich pending raw articles via Groq (paced; may take a few minutes)."""
    result = enrich_pending(db, limit)
    return ok(result, "Enrichment complete")


@router.get("/stats")
def ingestion_stats(
    _user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Counts of raw articles by intelligence_status."""
    return ok(get_stats(db), "Ingestion stats")
