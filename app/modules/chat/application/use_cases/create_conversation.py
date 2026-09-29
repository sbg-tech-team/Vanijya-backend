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
        # get_conv_send_info: one joined query for status + membership, instead
        # of get_conversation's full participant/last-message/unread-count
        # build — none of which this check needs.
        guard = self.repo.get_conv_send_info(conv_id, sender_id)
        if not guard:
            raise ConversationNotFoundError("Conversation not found.")
        if guard.status != ConversationStatus.ACTIVE:
            raise ConversationAccessDeniedError(
                "Can only create deals in an active conversation."
            )
        return self.repo.create_personal_deal(
            conv_id=conv_id, sender_id=sender_id, **deal_fields
        )


class OpenConversationUseCase:
    """Get or create the DM between two users. Idempotent."""

    def __init__(self, repo):
        self.repo = repo

    def execute(self, user_id: UUID, participant_id: UUID) -> dict:
        return self.repo.get_or_create_dm(user_id, participant_id)


class GetConversationPeerUseCase:
    """The other member of a DM, or None if `user_id` is not a member.

    Routers need this to address a socket event after a use case has already
    done the write — the recipient is a routing detail, not a business result.
    """

    def __init__(self, repo):
        self.repo = repo

    def execute(self, conv_id: UUID, user_id: UUID):
        guard = self.repo.get_conv_send_info(conv_id, user_id)
        return guard.receiver_id if guard else None
