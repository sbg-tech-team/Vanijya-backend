from uuid import UUID

from app.modules.chat.domain.exceptions import (
    ConversationAccessDeniedError,
    MessageNotFoundError,
    MessageDeleteNotAllowedError,
)


class MarkReadUseCase:
    def __init__(self, repo):
        self.repo = repo

    def execute(self, user_id: UUID, conv_id: UUID):
        if not self.repo.is_member(conv_id, user_id):
            # guard clause — reject non-members early
            raise ConversationAccessDeniedError(
                "The user is not a part of this conversation."
            )
        return self.repo.mark_read(conv_id, user_id)


class DeleteMessageUseCase:
    """Soft-delete a message. Only the sender may delete their own message."""

    def __init__(self, repo):
        self.repo = repo

    def execute(self, user_id: UUID, message_id: UUID):
        info = self.repo.soft_delete_message(message_id, user_id)
        if info is None:
            raise MessageNotFoundError(
                "Message not found or you cannot delete it."
            )
        return info
