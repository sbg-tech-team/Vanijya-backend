#!/usr/bin/env python3
"""
End-to-end test for the news_new ingestion + intelligence pipeline.

Spins up ONLY the news_new router in a FastAPI TestClient (auth dependency
overridden), then exercises every admin endpoint against the REAL database and
the REAL GNews + Groq APIs:

    GET  /news/admin/stats     (before)
    POST /news/admin/ingest    (live GNews fetch -> store raw, status=pending)
    POST /news/admin/enrich     (live Groq -> EnrichedArticle, status=enriched)
    GET  /news/admin/stats     (after)

Then it reads back one raw + one enriched row from the DB to show the data.

Usage (from backend/):
    python scripts/NEWSSS/test_news_new_pipeline.py
    python scripts/NEWSSS/test_news_new_pipeline.py --limit 3 --query "rice export"

Requires GNEWS_API_KEY and GROQ_API_KEY in .env. Each run spends 1 GNews request
and a few Groq calls (paced ~2/min, so --limit 3 takes ~1 minute).
"""
import argparse
import json
import sys
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.dependencies import get_current_user_id
from app.core.database.session import SessionLocal
from app.modules.news_new import router as news_new_router
from app.modules.news_new.ingestion.models import RawArticle
from app.modules.news_new.intelligence.models import EnrichedArticle


def build_client() -> TestClient:
    app = FastAPI()
    app.include_router(news_new_router)
    # Bypass auth — return a stable dummy user id.
    app.dependency_overrides[get_current_user_id] = lambda: uuid4()
    return TestClient(app)


def show(title: str, resp) -> dict:
    print(f"\n=== {title} -> HTTP {resp.status_code} ===")
    try:
        body = resp.json()
        print(json.dumps(body, indent=2, default=str)[:1500])
        return body
    except Exception:
        print(resp.text[:1500])
        return {}


def dump_sample_rows() -> None:
    """Read back the newest raw + its enriched row straight from the DB."""
    db = SessionLocal()
    try:
        raw = db.execute(
            select(RawArticle).order_by(RawArticle.platform_arrived_at.desc()).limit(1)
        ).scalar_one_or_none()
        if not raw:
            print("\n[DB] No raw articles found.")
            return
        print("\n=== Sample RawArticle (newest) ===")
        print(json.dumps({
            "id": str(raw.id),
            "external_id": raw.external_id,
            "title": raw.title,
            "source_name": raw.source_name,
            "source_country": raw.source_country,
            "published_at": str(raw.published_at),
            "intelligence_status": raw.intelligence_status,
            "has_raw_metadata": bool(raw.raw_metadata),
        }, indent=2))

        enr = db.execute(
            select(EnrichedArticle).order_by(EnrichedArticle.generated_at.desc()).limit(1)
        ).scalar_one_or_none()
        if not enr:
            print("\n[DB] No enriched articles yet.")
            return
        print("\n=== Sample EnrichedArticle (newest) ===")
        print(json.dumps({
            "raw_article_id": str(enr.raw_article_id),
            "primary_factor": enr.primary_factor,
            "geo_category": enr.geo_category,
            "factor_scores": enr.factor_scores,
            "summary_bullets": enr.summary_bullets,
            "impact": {
                "direction": enr.impact_direction,
                "score": enr.impact_score,
                "factor": enr.impact_factor,
                "explanation": enr.impact_explanation,
            },
            "role_relevance": {
                "trader": enr.role_trader,
                "broker": enr.role_broker,
                "exporter": enr.role_exporter,
            },
            "model_version": enr.model_version,
        }, indent=2))
    finally:
        db.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", default=None,
                    help="GNews query for single-query mode. Omit to run the rotation pool batch.")
    ap.add_argument("--limit", type=int, default=20, help="Max pending articles to enrich")
    args = ap.parse_args()

    client = build_client()

    show("STATS (before)", client.get("/news/admin/stats"))
    ingest_params = {"query": args.query} if args.query else {}
    mode = f"single-query '{args.query}'" if args.query else "rotation pool batch"
    print(f"\n[ingest] mode: {mode}")
    show("INGEST", client.post("/news/admin/ingest", params=ingest_params))

    print(f"\n[enrich] calling /news/admin/enrich?limit={args.limit} "
          f"(paced ~2/min, please wait ~{args.limit * 30}s) ...")
    show("ENRICH", client.post("/news/admin/enrich", params={"limit": args.limit}))

    show("STATS (after)", client.get("/news/admin/stats"))
    dump_sample_rows()

    print("\nDONE.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
