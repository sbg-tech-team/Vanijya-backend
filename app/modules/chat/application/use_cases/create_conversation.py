from uuid import UUID

from app.modules.chat.domain.value_objects import ConversationStatus
from app.modules.chat.domain.exceptions import (
    ConversationAlreadyExistsError,
    ConversationNotFoundError,
    ConversationAccessDeniedError,
    DealAccessDeniedError,
    PersonalDealNotFoundError,
)


class CreatePersonalDealUseCase:
    def __init__(self, repo):
        self.repo = repo

    def execute(self, sender_id: UUID, conv_id: UUID, **deal_fields):
        conv = self.repo.get_conversation(conv_id, sender_id)
        if not conv:
            raise ConversationNotFoundError("Conversation not found.")
        if conv.status != ConversationStatus.ACTIVE:
            raise ConversationAccessDeniedError(
                "Can only create deals in an active conversation."
            )
        return self.repo.create_personal_deal(
            conv_id=conv_id, sender_id=sender_id, **deal_fields
        )
