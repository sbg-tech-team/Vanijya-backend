"""
Intelligence service — turn a pending RawArticle into an EnrichedArticle.

Flow per article:
    build input text  ->  Groq call  ->  validate enums (retry once)
                      ->  compute role_relevance from the matrix
                      ->  write EnrichedArticle + flip raw status to "enriched"

role_relevance is COMPUTED from RELEVANCY_MATRIX, never from the LLM. On a
persistent bad/parse failure the raw row is marked "failed" (no partial write).
"""
import logging
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.news_new.config import (
    LLM_CONTENT_CHAR_CAP,
    STATUS_ENRICHED,
    STATUS_FAILED,
    role_relevance_for,
)
from app.modules.news_new.ingestion import service as ingestion_service
from app.modules.news_new.intelligence.models import EnrichedArticle
from app.modules.news_new.intelligence.providers.groq import GroqEnricher
from app.modules.news_new.intelligence.schemas import LLMEnrichment

if TYPE_CHECKING:  # typing only — no runtime ORM coupling across slices
    from app.modules.news_new.ingestion.models import RawArticle

log = logging.getLogger(__name__)


def build_input_text(article: "RawArticle") -> str:
    parts = [f"TITLE: {article.title or ''}"]
    if article.description:
        parts.append(f"DESCRIPTION: {article.description}")
    if article.content:
        parts.append(f"CONTENT: {article.content[:LLM_CONTENT_CHAR_CAP]}")
    return "\n".join(parts)


def _call_and_validate(enricher: GroqEnricher, text: str) -> LLMEnrichment:
    """One Groq call + enum validation, with a single retry on bad output."""
    last_err: Exception | None = None
    for _ in range(2):
        raw = enricher.enrich(text)
        try:
            return LLMEnrichment.model_validate(raw)
        except Exception as e:  # parse / enum failure -> retry once
            last_err = e
            log.warning("Enrichment validation failed, retrying: %s", e)
    raise ValueError(f"enrichment validation failed after retry: {last_err}")


def enrich_article(
    db: Session,
    article: "RawArticle",
    enricher: GroqEnricher,
) -> EnrichedArticle | None:
    """
    Enrich one raw article. Returns the EnrichedArticle on success, or None if
    the article was marked failed. Commits per article (crash-safe progress).
    """
    try:
        out = _call_and_validate(enricher, build_input_text(article))
    except Exception as e:
        log.warning("Enrich FAILED for %s: %s", article.external_id, e)
        ingestion_service.mark_status(db, article, STATUS_FAILED)
        db.commit()
        return None

    rel = role_relevance_for(out.primary_factor)
    enriched = EnrichedArticle(
        raw_article_id=article.id,
        primary_factor=out.primary_factor,
        factor_scores=[fs.model_dump() for fs in out.factor_scores],
        geo_category=out.geo_category,
        summary_bullets=out.summary_bullets,
        impact_direction=out.impact.direction,
        impact_score=out.impact.score,
        impact_factor=out.impact.factor,
        impact_explanation=out.impact.explanation,
        role_trader=rel["trader"],
        role_broker=rel["broker"],
        role_exporter=rel["exporter"],
        model_version=enricher.model,
    )
    db.add(enriched)
    ingestion_service.mark_status(db, article, STATUS_ENRICHED)
    db.commit()
    return enriched


def enrich_pending(db: Session, limit: int, enricher: GroqEnricher | None = None) -> dict:
    """Enrich up to `limit` pending articles, paced by the enricher's limiter."""
    enricher = enricher or GroqEnricher()
    pending = ingestion_service.get_pending_articles(db, limit)
    total = len(pending)
    enriched = failed = 0
    if total:
        log.info("news_new.enrich: starting — %d pending article(s) to enrich (limit %d)", total, limit)
    calls_before = enricher.calls
    for i, article in enumerate(pending, 1):
        result = enrich_article(db, article, enricher)
        if result is None:
            failed += 1
            log.info("news_new.enrich [%d/%d] FAILED — %s", i, total, (article.title or "")[:70])
        else:
            enriched += 1
            log.info("news_new.enrich [%d/%d] OK — %s/%s — %s",
                     i, total, result.primary_factor, result.impact_direction, (article.title or "")[:70])
    remaining = ingestion_service.count_pending(db)
    groq_calls = enricher.calls - calls_before
    if total:
        log.info("news_new.enrich: done — %d Groq call(s), %d enriched, %d failed, %d still pending",
                 groq_calls, enriched, failed, remaining)
    return {
        "enriched": enriched,
        "failed": failed,
        "groq_calls": groq_calls,
        "remaining_pending": remaining,
    }


def get_enriched(db: Session, raw_article_id) -> EnrichedArticle | None:
    return db.execute(
        select(EnrichedArticle).where(EnrichedArticle.raw_article_id == raw_article_id)
    ).scalar_one_or_none()


def count_enriched(db: Session) -> int:
    return db.execute(select(func.count()).select_from(EnrichedArticle)).scalar_one()
