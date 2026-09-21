from datetime import datetime
from typing import Optional
from uuid import UUID

from app.modules.chat.domain.exceptions import (
    ConversationAccessDeniedError,
    MemberNotFoundError,
)


class GetConversationsUseCase:
    def __init__(self, repo):
        self.repo = repo

    def execute(self, user_id: UUID, page: int = 1, per_page: int = 20):
        return self.repo.get_conversations(user_id, page, per_page)


class GetMessagesUseCase:
    def __init__(self, repo):
        self.repo = repo

    def execute(
        self,
        user_id: UUID,
        conv_id: UUID,
        before: Optional[datetime] = None,
        limit: int = 50,
    ):
        if not self.repo.is_member(conv_id, user_id):
            raise ConversationAccessDeniedError(
                "The user is not a part of this conversation."
            )
        # Serve stored translations inline when this reader has continuous mode
        # on: without it, scroll-back, a thread reopen or a dropped socket all
        # show the untranslated original again.
        target = self.repo.reader_continuous_target(user_id, conv_id)
        # min() caps the page size at 100 messages
        return self.repo.get_messages("dm", conv_id, before, min(limit, 100), translate_to=target)


class GetGroupMessagesUseCase:
    def __init__(self, repo):
        self.repo = repo

    def execute(
        self,
        user_id: UUID,
        group_id: UUID,
        before: Optional[datetime] = None,
        limit: int = 50,
    ):
        member_role = self.repo.get_group_member_role(group_id, user_id)
        if member_role is None:
            raise MemberNotFoundError("Not a member of this group.")
        return self.repo.get_messages("group", group_id, before, min(limit, 100))


class GetAllChatsUseCase:
    """Unified chat list — DMs and groups merged, newest activity first."""

    def __init__(self, repo):
        self.repo = repo

    def execute(self, user_id: UUID, page: int = 1, per_page: int = 20):
        return self.repo.get_all_chats(user_id, page, per_page)


class GetShareRecipientsUseCase:
    def __init__(self, repo):
        self.repo = repo

    def execute(self, user_id: UUID):
        return self.repo.get_share_recipients(user_id)
