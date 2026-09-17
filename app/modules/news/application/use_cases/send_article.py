"""
Send article use case — in-app article sharing via the Chat module.

Ported from app_v1_backup/modules/news_new/news_user_interaction/service.py
(send_article). Delivers to multiple DM conversations and/or groups in one
call, silently skipping recipients that fail permission checks (partial
delivery is expected/normal, not an error).

Delivery itself belongs to chat, so it is handed in as a use case
(DeliverSharedContentUseCase) rather than reached for through chat's
repository.
"""
from __future__ import annotations

import logging
from uuid import UUID

from app.modules.news.domain.exceptions import ArticleNotFoundError
from app.modules.news.domain.interfaces.repository import INewsRepository
from app.recommendation.amplify import commodity_ids_for, write_news_signals
from app.recommendation.session_taste import ActionType

log = logging.getLogger(__name__)


class SendArticleUseCase:

    def __init__(self, repo: INewsRepository, deliver_uc) -> None:
        self._repo = repo
        self._deliver = deliver_uc

    def execute(
        self,
        sender_profile_id: int,
        sender_user_id: UUID,
        article_id: UUID,
        dm_conversation_ids: list[UUID],
        group_ids: list[UUID],
        caption: str | None,
        rc=None,
    ) -> dict:
        """
        Returns {"share_count", "dm_deliveries": [(receiver_id, message)],
        "group_deliveries": [(group_id, message)]} — the router emits
        WebSocket events from the delivery lists and returns
        {share_count, delivered_to=len(dm)+len(group)}.
        """
        raw = self._repo.get_raw_article(article_id)
        if raw is None:
            raise ArticleNotFoundError(str(article_id))

        dm_deliveries, group_deliveries = self._deliver.execute(
            sender_id=sender_user_id,
            message_type="news_article",
            dm_conversation_ids=dm_conversation_ids,
            group_ids=group_ids,
            caption=caption,
            require_active_dm=False,
            article_id=article_id,
        )

        self._repo.record_share(sender_profile_id, article_id, platform=None)
        self._repo.adjust_article_stats(article_id, "share_count", 1)
        self._repo.commit()

        try:
            enriched = self._repo.get_enriched_article(article_id)
            if enriched is not None:
                if enriched.primary_factor:
                    self._repo.upsert_taste(
                        profile_id=sender_profile_id,
                        dimension_type="category",
                        dimension_key=enriched.primary_factor,
                        positive_delta=4.0,
                    )
                write_news_signals(
                    rc, sender_profile_id,
                    commodity_ids_for(self._repo, enriched.commodity_tags or []),
                    enriched.location_city, enriched.location_state, ActionType.SHARE,
                )
            self._repo.commit()
        except Exception:
            log.exception("send_article: taste update failed for article %s", article_id)

        stats = self._repo.get_article_stats(article_id)
        share_count = stats.share_count if stats else 0

        return {
            "share_count": share_count,
            "dm_deliveries": dm_deliveries,
            "group_deliveries": group_deliveries,
        }
