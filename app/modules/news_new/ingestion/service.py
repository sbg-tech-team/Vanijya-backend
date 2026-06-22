"""
Ingestion service — fetch from a provider, normalize, store raw rows.

NO repository layer: DB queries live here directly. Dedup is on `external_id`
only (title-similarity near-dup detection is deferred).
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.news_new.config import (
    GNEWS_DEFAULT_COUNTRY,
    GNEWS_QUERIES_PER_RUN,
    STATUS_ENRICHED,
    STATUS_FAILED,
    STATUS_PENDING,
)
from app.modules.news_new.ingestion.models import RawArticle
from app.modules.news_new.ingestion.news_queries import QUERIES
from app.modules.news_new.ingestion.providers.base import BaseNewsProvider

log = logging.getLogger(__name__)

_ROTATION_SLOT_SECONDS = 1800  # 30 min — one rotation step per scheduled run


def ingest_from_provider(
    db: Session,
    provider: BaseNewsProvider,
    query: str,
    country: str | None = GNEWS_DEFAULT_COUNTRY,
) -> dict:
    """
    One fetch → normalize → insert new RawArticle rows (status=pending).
    Returns {provider, query, fetched, new, skipped}. Commits once.
    """
    raw_items = provider.fetch(query, country)
    fetched = len(raw_items)
    new = skipped = 0
    seen: set[str] = set()

    for item in raw_items:
        canon = provider.to_canonical(item, query)
        ext = canon.get("external_id")
        url = canon.get("article_url")
        if not ext or not url:
            skipped += 1
            continue
        # de-dupe within this batch and against the DB
        if ext in seen or _exists(db, ext):
            skipped += 1
            continue
        seen.add(ext)

        db.add(_to_model(canon))
        new += 1

    db.commit()
    log.info("news_new.ingest[%s]: fetched=%d new=%d skipped=%d", provider.name, fetched, new, skipped)
    return {"provider": provider.name, "query": query, "fetched": fetched, "new": new, "skipped": skipped}


def select_queries_for_run(per_run: int = GNEWS_QUERIES_PER_RUN) -> list[dict]:
    """
    Pick the next `per_run` query specs from the rotation pool, advancing by
    wall-clock 30-min slot so consecutive scheduled runs cover the whole pool.
    Time-derived (no stored cursor) — survives restarts, no extra table.
    """
    n = len(QUERIES)
    if n == 0 or per_run <= 0:
        return []
    per_run = min(per_run, n)
    slot = int(datetime.now(timezone.utc).timestamp() // _ROTATION_SLOT_SECONDS)
    start = (slot * per_run) % n
    return [QUERIES[(start + i) % n] for i in range(per_run)]


def ingest_rotation(
    db: Session,
    provider: BaseNewsProvider,
    per_run: int = GNEWS_QUERIES_PER_RUN,
) -> dict:
    """
    Run a rotating batch of queries in one ingest pass (more articles per run).
    Each query is one provider request; results aggregate across the batch.
    """
    specs = select_queries_for_run(per_run)
    agg = {"fetched": 0, "new": 0, "skipped": 0}
    per_query: list[dict] = []
    for spec in specs:
        res = ingest_from_provider(db, provider, spec["q"], country=spec.get("country"))
        for k in agg:
            agg[k] += res[k]
        per_query.append({"query": spec["q"], "country": spec.get("country"), **{k: res[k] for k in agg}})
    log.info("news_new.ingest_rotation: queries=%d %s", len(specs), agg)
    return {"provider": provider.name, "queries": len(specs), **agg, "per_query": per_query}


def _exists(db: Session, external_id: str) -> bool:
    return db.execute(
        select(RawArticle.id).where(RawArticle.external_id == external_id)
    ).first() is not None


def _to_model(canon: dict) -> RawArticle:
    return RawArticle(
        external_id=canon["external_id"],
        title=(canon.get("title") or "")[:500],
        description=canon.get("description"),
        content=canon.get("content"),
        article_url=canon["article_url"],
        image_url=canon.get("image_url"),
        published_at=canon["published_at"],
        language=canon.get("language"),
        source_name=canon.get("source_name"),
        source_url=canon.get("source_url"),
        source_country=canon.get("source_country"),
        authors=canon.get("authors") or [],
        is_duplicate=bool(canon.get("is_duplicate")),
        api_summary=canon.get("api_summary"),
        raw_metadata=canon.get("raw_metadata") or {},
        intelligence_status=STATUS_PENDING,
    )


# ── Queries used by the intelligence slice / admin ─────────────────────────── #

def get_pending_articles(db: Session, limit: int) -> list[RawArticle]:
    """Oldest-arrived pending rows first (FIFO enrichment)."""
    return list(
        db.execute(
            select(RawArticle)
            .where(RawArticle.intelligence_status == STATUS_PENDING)
            .order_by(RawArticle.platform_arrived_at.asc())
            .limit(limit)
        ).scalars()
    )


def mark_status(db: Session, article: RawArticle, status: str) -> None:
    """Update a raw row's intelligence_status. Does NOT commit (caller owns txn)."""
    article.intelligence_status = status
    db.add(article)


def count_pending(db: Session) -> int:
    return db.execute(
        select(func.count())
        .select_from(RawArticle)
        .where(RawArticle.intelligence_status == STATUS_PENDING)
    ).scalar_one()


def get_stats(db: Session) -> dict:
    rows = db.execute(
        select(RawArticle.intelligence_status, func.count())
        .group_by(RawArticle.intelligence_status)
    ).all()
    by_status = {status: cnt for status, cnt in rows}
    return {
        "total": sum(by_status.values()),
        "pending": by_status.get(STATUS_PENDING, 0),
        "enriched": by_status.get(STATUS_ENRICHED, 0),
        "failed": by_status.get(STATUS_FAILED, 0),
    }
