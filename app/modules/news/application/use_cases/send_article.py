"""
Send article use case — in-app article sharing via the Chat module.

Ported from app_v1_backup/modules/news_new/news_user_interaction/service.py
(send_article). Delivers to multiple DM conversations and/or groups in one
call, silently skipping recipients that fail permission checks (partial
delivery is expected/normal, not an error).

The ChatRepository is injected as a callable factory so this use case never
imports from the chat module at module scope (only inside execute(), to
avoid a cross-module import cycle at app boot).
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

    def __init__(self, repo: INewsRepository) -> None:
        self._repo = repo

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
        from app.modules.chat.data.repository import ChatRepository

        raw = self._repo.get_raw_article(article_id)
        if raw is None:
            raise ArticleNotFoundError(str(article_id))

        chat_repo = ChatRepository(self._repo.session)

        dm_deliveries: list[tuple] = []
        for conv_id in dm_conversation_ids:
            guard = chat_repo.get_conv_send_info(conv_id, sender_user_id)
            if guard:
                msg = chat_repo.save_message(
                    context_type="dm",
                    context_id=conv_id,
                    sender_id=sender_user_id,
                    message_type="news_article",
                    article_id=article_id,
                    body=caption,
                )
                dm_deliveries.append((guard.receiver_id, msg))

        group_deliveries: list[tuple] = []
        for group_id in group_ids:
            chat_perm = chat_repo.get_group_chat_perm(group_id)
            member_role = chat_repo.get_group_member_role(group_id, sender_user_id)
            is_frozen = chat_repo.is_group_member_frozen(group_id, sender_user_id)
            if (
                chat_perm and member_role and not is_frozen
                and (chat_perm == "all_members" or member_role == "admin")
            ):
                msg = chat_repo.save_message(
                    context_type="group",
                    context_id=group_id,
                    sender_id=sender_user_id,
                    message_type="news_article",
                    article_id=article_id,
                    body=caption,
                )
                group_deliveries.append((group_id, msg))

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
                    commodity_ids_for(self._repo.session, enriched.commodity_tags or []),
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
