"""
Admin routes — pipeline control and operational stats.

Paths match app_v1_backup/modules/news_new/ingestion/router.py (prefix
"/admin", mounted under "/news" by router.py). Auth: any authenticated user
(matches app_v1_backup exactly — there is no staff/admin role gate on these
endpoints in production today).

POST /news/admin/ingest   -> trigger one ingest rotation
POST /news/admin/enrich   -> trigger one enrich batch
GET  /news/admin/stats    -> ingestion stats by status
POST /news/admin/archive  -> trigger the archive job (soft-delete old articles) [additive]
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.dependencies import get_current_user_id
from app.modules.news.application.use_cases.enrich_articles import EnrichArticlesUseCase
from app.modules.news.application.use_cases.ingest_articles import IngestArticlesUseCase
from app.modules.news.presentation.dependencies import (
    get_enrich_use_case,
    get_ingest_use_case,
    get_repo,
)
from app.modules.news.presentation.schemas import (
    EnrichResultOut,
    IngestResultOut,
    IngestionStatsOut,
)
from app.shared.utils.response import ok

router = APIRouter(prefix="/admin", tags=["News Ingestion"], dependencies=[Depends(get_current_user_id)])


@router.post("/ingest")
def trigger_ingest(
    use_case: Annotated[IngestArticlesUseCase, Depends(get_ingest_use_case)],
):
    result = use_case.execute()
    out = IngestResultOut(**result)
    return ok(out.model_dump(mode="json"), "Ingestion complete")


@router.post("/enrich")
def trigger_enrich(
    use_case: Annotated[EnrichArticlesUseCase, Depends(get_enrich_use_case)],
):
    result = use_case.execute()
    out = EnrichResultOut(**result)
    return ok(out.model_dump(mode="json"), "Enrichment complete")


@router.get("/stats")
def get_ingestion_stats(
    repo=Depends(get_repo),
):
    stats = repo.get_ingestion_stats()
    out = IngestionStatsOut(
        pending=stats.get("pending", 0),
        processing=stats.get("processing", 0),
        enriched=stats.get("enriched", 0),
        failed=stats.get("failed", 0),
    )
    return ok(out.model_dump(mode="json"), "Ingestion stats")


@router.post("/archive")
def trigger_archive(
    repo=Depends(get_repo),
):
    count = repo.archive_old_raw_articles()
    return ok({"archived": count}, "Archive complete")
