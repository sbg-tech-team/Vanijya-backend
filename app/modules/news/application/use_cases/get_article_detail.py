"""
Get article detail use case.

Returns a fully populated NewsCardDetail for the given article_id + profile.
Matches app_v1_backup: an article missing its enrichment is still returned
(enriched fields simply null) - only a missing raw article is a 404.

The open_article event is NOT recorded here - the client sends it separately
via the record_interaction endpoint so the interaction batch can deduplicate it.
"""
from __future__ import annotations

from datetime import datetime, timezone

from uuid import UUID

from app.modules.news.domain.entities import NewsCardDetail
from app.modules.news.domain.exceptions import ArticleNotFoundError
from app.modules.news.domain.interfaces.repository import INewsRepository


class GetArticleDetailUseCase:

    def __init__(self, repo: INewsRepository) -> None:
        self._repo = repo

    def execute(self, profile_id: int, article_id: UUID) -> NewsCardDetail:
        raw = self._repo.get_raw_article(article_id)
        if raw is None:
            raise ArticleNotFoundError(str(article_id))

        enriched = self._repo.get_enriched_article(article_id)
        stats = self._repo.get_article_stats(article_id)
        is_liked = self._repo.get_like_state(profile_id, article_id)
        is_saved = self._repo.get_save_state(profile_id, article_id)

        return NewsCardDetail(
            article_id=raw.id,
            title=raw.title,
            platform_arrived_at=raw.platform_arrived_at,
            time_on_platform=_compute_time_on_platform(raw.platform_arrived_at),
            image_url=raw.image_url,
            source_name=raw.source_name,
            summary_bullets=enriched.summary_bullets if enriched else None,
            primary_factor=enriched.primary_factor if enriched else None,
            geo_category=enriched.geo_category if enriched else None,
            is_government=enriched.is_government if enriched else False,
            impact_direction=enriched.impact_direction if enriched else None,
            impact_score=enriched.impact_score if enriched else None,
            like_count=stats.like_count if stats else 0,
            share_count=stats.share_count if stats else 0,
            is_liked=is_liked,
            is_saved=is_saved,
            # Detail-only fields
            description=raw.description,
            article_url=raw.article_url,
            source_url=raw.source_url,
            published_at=raw.published_at,
            impact_explanation=enriched.impact_explanation if enriched else None,
            impact_factor=enriched.impact_factor if enriched else None,
            factor_scores=enriched.factor_scores if enriched else None,
            view_count=stats.view_count if stats else None,
            save_count=stats.save_count if stats else None,
        )


def _compute_time_on_platform(platform_arrived_at: datetime) -> str:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    arrived = platform_arrived_at.replace(tzinfo=None) if platform_arrived_at.tzinfo else platform_arrived_at
    delta = now - arrived
    hours = int(delta.total_seconds() / 3600)
    if hours < 24:
        return f"{max(1, hours)}h"
    days = delta.days
    if days == 1:
        return "Yesterday"
    return f"{days} days ago"
