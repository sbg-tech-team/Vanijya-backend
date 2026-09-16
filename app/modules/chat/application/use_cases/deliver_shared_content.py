"""Deliver a shared item (a post, a news article) into DMs and group chats.

Chat owns who may receive a message, so the post and news share flows call this
instead of writing chat rows themselves. Delivery is partial by design: a
recipient that fails its permission check is skipped, not an error — the share
still succeeds for everyone else.
"""
from uuid import UUID

from app.modules.chat.domain.value_objects import ConversationStatus


class DeliverSharedContentUseCase:
    def __init__(self, repo):
        self.repo = repo

    def execute(
        self,
        sender_id: UUID,
        message_type: str,
        dm_conversation_ids: list[UUID],
        group_ids: list[UUID],
        caption: str | None = None,
        require_active_dm: bool = True,
        **content_ref,
    ) -> tuple[list[tuple], list[tuple]]:
        """Returns (dm_deliveries, group_deliveries) as [(recipient, message)].

        `content_ref` carries the reference column for this message type —
        `post_id=...` or `article_id=...`.
        """
        dm_deliveries: list[tuple] = []
        for conv_id in dm_conversation_ids:
            guard = self.repo.get_conv_send_info(conv_id, sender_id)
            if not guard:
                continue
            if require_active_dm and guard.status != ConversationStatus.ACTIVE:
                continue
            msg = self.repo.save_message(
                context_type="dm",
                context_id=conv_id,
                sender_id=sender_id,
                message_type=message_type,
                body=caption,
                **content_ref,
            )
            dm_deliveries.append((guard.receiver_id, msg))

        group_deliveries: list[tuple] = []
        for group_id in group_ids:
            if not self._may_post_to_group(group_id, sender_id):
                continue
            msg = self.repo.save_message(
                context_type="group",
                context_id=group_id,
                sender_id=sender_id,
                message_type=message_type,
                body=caption,
                **content_ref,
            )
            group_deliveries.append((group_id, msg))

        return dm_deliveries, group_deliveries

    def _may_post_to_group(self, group_id: UUID, user_id: UUID) -> bool:
        chat_perm = self.repo.get_group_chat_perm(group_id)
        member_role = self.repo.get_group_member_role(group_id, user_id)
        if not chat_perm or not member_role:
            return False
        if self.repo.is_group_member_frozen(group_id, user_id):
            return False
        return chat_perm == "all_members" or member_role == "admin"
