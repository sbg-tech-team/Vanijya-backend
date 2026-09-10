from typing import Optional
from uuid import UUID

from app.modules.chat.domain.value_objects import ConversationStatus
from app.modules.chat.domain.exceptions import (
    ConversationNotFoundError,
    ConversationBlockedError,
    GroupChatSendNotAllowedError,
    MemberNotFoundError,
    ChatPermissionDeniedError,
)


class SendMessageUseCase:
    def __init__(self, repo):
        self.repo = repo

    def execute(
        self,
        sender_id: UUID,
        conv_id: UUID,
        body: Optional[str] = None,
        message_type: str = "text",
        media_urls: Optional[list[str]] = None,
        media_metadata: Optional[dict] = None,
        location_lat: Optional[float] = None,
        location_lon: Optional[float] = None,
        reply_to_id: Optional[UUID] = None,
        deal_id: Optional[UUID] = None,
        personal_deal_id: Optional[UUID] = None,
        post_id: Optional[int] = None,
    ):
        guard = self.repo.get_conv_send_info(conv_id, sender_id)
        if not guard:
            raise ConversationNotFoundError("Conversation not found.")
        if guard.status == ConversationStatus.BLOCKED:
            raise ConversationBlockedError("Blocked conversation.")
        if post_id is not None and not self.repo.post_exists(post_id):
            raise ValueError("Post not found.")

        message = self.repo.save_message(
            context_type="dm",
            context_id=conv_id,
            sender_id=sender_id,
            body=body,
            message_type=message_type,
            media_urls=media_urls,
            media_metadata=media_metadata,
            location_lat=location_lat,
            location_lon=location_lon,
            reply_to_id=reply_to_id,
            deal_id=deal_id,
            personal_deal_id=personal_deal_id,
            post_id=post_id,
        )
        # Return the receiver id too so the router can emit without a second guard query.
        return message, guard.receiver_id


class SendGroupMessageUseCase:
    """
    Group chat send rules:
      - Sender must be a group member
      - Sender must not be frozen
      - If chat_perm == 'admins_only', sender must be admin
    """

    def __init__(self, repo):
        self.repo = repo

    def execute(
        self,
        sender_id: UUID,
        group_id: UUID,
        body: Optional[str] = None,
        message_type: str = "text",
        media_urls: Optional[list[str]] = None,
        media_metadata: Optional[dict] = None,
        location_lat: Optional[float] = None,
        location_lon: Optional[float] = None,
        reply_to_id: Optional[UUID] = None,
        deal_id: Optional[UUID] = None,
        post_id: Optional[int] = None,
    ):
        chat_perm = self.repo.get_group_chat_perm(group_id)
        if chat_perm is None:
            raise ConversationNotFoundError("Group not found.")

        member_role = self.repo.get_group_member_role(group_id, sender_id)
        if member_role is None:
            raise MemberNotFoundError("Not a member of this group.")

        if self.repo.is_group_member_frozen(group_id, sender_id):
            raise GroupChatSendNotAllowedError(
                "You are frozen in this group and cannot send messages."
            )

        if chat_perm == "admins_only" and member_role != "admin":
            raise GroupChatSendNotAllowedError(
                "Only admins can send messages in this group."
            )

        if post_id is not None and not self.repo.post_exists(post_id):
            raise ValueError("Post not found.")

        return self.repo.save_message(
            context_type="group",
            context_id=group_id,
            sender_id=sender_id,
            body=body,
            message_type=message_type,
            media_urls=media_urls,
            media_metadata=media_metadata,
            location_lat=location_lat,
            location_lon=location_lon,
            reply_to_id=reply_to_id,
            deal_id=deal_id,
            post_id=post_id,
        )
        # personal_deal_id is not passed here — group messages can only reference group_deals
