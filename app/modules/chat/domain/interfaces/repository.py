from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # annotations only — no runtime import, no cycle
    from app.modules.chat.domain.entities import (
        ChatListItem,
        ConvSendGuard,
        ConversationEntity,
        GroupConversationEntity,
        MessageEntity,
        ShareRecipientsResult,
    )


class IChatRepository(ABC):
    """Every database access in the chat module goes through this interface."""

    @abstractmethod
    def get_conversation(self, conv_id: UUID, requesting_user_id: UUID) -> Optional[ConversationEntity]:
        ...

    @abstractmethod
    def get_conversations(self, user_id: UUID, page: int, per_page: int) -> list[ConversationEntity]:
        ...

    @abstractmethod
    def save_message(self, context_type: str, context_id: UUID, sender_id: UUID, body: Optional[str] = None, message_type: str = 'text', media_urls: Optional[list[str]] = None, media_metadata: Optional[dict] = None, location_lat: Optional[float] = None, location_lon: Optional[float] = None, reply_to_id: Optional[UUID] = None, deal_id: Optional[UUID] = None, personal_deal_id: Optional[UUID] = None, post_id: Optional[int] = None, article_id: Optional[UUID] = None) -> MessageEntity:
        ...

    @abstractmethod
    def reader_continuous_target(self, user_id: UUID, conv_id: UUID) -> Optional[str]:
        """Language to serve stored translations in, or None if this reader has
        continuous translation off for this conversation."""
        ...

    @abstractmethod
    def get_messages(
        self,
        context_type: str,
        context_id: UUID,
        before: Optional[datetime],
        limit: int,
        translate_to: Optional[str] = None,
    ) -> list[MessageEntity]:
        ...

    @abstractmethod
    def mark_read(self, conv_id: UUID, user_id: UUID) -> None:
        ...

    @abstractmethod
    def soft_delete_message(self, message_id: UUID, user_id: UUID) -> Optional[dict]:
        """Flip is_deleted for a message the caller owns. Returns context + the"""
        ...

    @abstractmethod
    def is_member(self, conv_id: UUID, user_id: UUID) -> bool:
        ...

    @abstractmethod
    def get_conv_send_info(self, conv_id: UUID, sender_id: UUID) -> Optional[ConvSendGuard]:
        """Single JOIN replacing multiple queries: verifies membership, fetches status + initiator + receiver + sender profile."""
        ...

    @abstractmethod
    def create_personal_deal(self, conv_id: UUID, sender_id: UUID, commodity_id: int, title: str, caption: str, grain_type: str, grain_size: str, commodity_quantity: float, quantity_unit: str, commodity_price: float, price_type: str, image_urls: Optional[list[str]]) -> MessageEntity:
        ...

    @abstractmethod
    def post_exists(self, post_id: int) -> bool:
        ...

    @abstractmethod
    def get_share_recipients(self, user_id: UUID) -> ShareRecipientsResult:
        """Two queries — no N+1."""
        ...

    @abstractmethod
    def is_group_member(self, group_id: UUID, user_id: UUID) -> bool:
        ...

    @abstractmethod
    def dm_member_ids(self, conv_id: UUID) -> list[str]:
        ...

    @abstractmethod
    def mark_delivered_and_get_peer(self, conv_id: UUID, user_id: UUID, now):
        """Stamp last_delivered_at for this member and return the other member's id."""
        ...

    @abstractmethod
    def get_or_create_dm(self, user_id: UUID, target_user_id: UUID) -> dict:
        """Get existing DM between user and target, or create a new ACTIVE one. Idempotent."""
        ...

    @abstractmethod
    def get_group_conversations(self, user_id: UUID) -> list[GroupConversationEntity]:
        """Every group the user belongs to, built as a chat-list entity."""
        ...

    @abstractmethod
    def get_all_chats(self, user_id: UUID, page: int, per_page: int) -> list[ChatListItem]:
        """DMs + groups merged into one list, newest activity first."""
        ...

    @abstractmethod
    def get_group_member_role(self, group_id: UUID, user_id: UUID) -> Optional[str]:
        ...

    @abstractmethod
    def is_group_member_frozen(self, group_id: UUID, user_id: UUID) -> bool:
        ...

    @abstractmethod
    def get_group_chat_perm(self, group_id: UUID) -> Optional[str]:
        ...

    @abstractmethod
    def get_group_member_ids(self, group_id: UUID) -> list[UUID]:
        ...
