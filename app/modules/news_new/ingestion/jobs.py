"""
Scheduled news pipeline entrypoint.

Wired into app.core.scheduler to run every 30 min:
    GNews ingest  ->  enrich the freshly-pending rows (paced under rate caps).

Each step owns its own commits, so a crash mid-enrichment never loses prior work.
"""
import logging

from app.core.database.session import SessionLocal
from app.modules.news_new.config import ENRICH_BATCH_LIMIT
from app.modules.news_new.ingestion.providers.gnews import GNewsProvider
from app.modules.news_new.ingestion.service import ingest_rotation
from app.modules.news_new.intelligence.service import enrich_pending

log = logging.getLogger(__name__)


def run_news_pipeline() -> dict:
    """
    Scheduled pipeline: rotate through the query pool (a few queries per run),
    then enrich the freshly-pending rows. Safe to call from the scheduler.
    """
    db = SessionLocal()
    try:
        ingest = ingest_rotation(db, GNewsProvider())
        enrich = enrich_pending(db, ENRICH_BATCH_LIMIT)
        log.info("news_new pipeline: ingest=%s enrich=%s", ingest, enrich)
        return {"ingest": ingest, "enrich": enrich}
    except Exception:
        db.rollback()
        log.exception("news_new pipeline run failed")
        raise
    finally:
        db.close()
