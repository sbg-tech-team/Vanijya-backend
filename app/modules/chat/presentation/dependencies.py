from dataclasses import dataclass

from sqlalchemy.orm import Session
from fastapi import Depends
from app.modules.chat.data.repository import ChatRepository
from app.modules.chat.application.use_cases.service import (
    GetConversationsUseCase,
    GetMessagesUseCase,
    SendMessageUseCase,
    SendGroupMessageUseCase,
    GetGroupMessagesUseCase,
    MarkReadUseCase,
    CreatePersonalDealUseCase,
    DeleteMessageUseCase,
    GetShareRecipientsUseCase,
    GetAllChatsUseCase,
    GetGroupConversationsUseCase,
)
from app.modules.chat.application.use_cases.create_conversation import (
    GetConversationPeerUseCase,
    OpenConversationUseCase,
)
from app.modules.chat.application.use_cases.deliver_shared_content import (
    DeliverSharedContentUseCase,
)
from app.modules.chat.application.use_cases.socket_events import (
    CanJoinGroupRoomUseCase,
    MarkDeliveredUseCase,
    RelayTypingUseCase,
)
from app.dependencies import get_db

def get_chat_repo(db: Session = Depends(get_db)) -> ChatRepository:
    return ChatRepository(db)

def get_conversations_uc(repo: ChatRepository = Depends(get_chat_repo)) -> GetConversationsUseCase:
    return GetConversationsUseCase(repo)

def get_messages_uc(repo: ChatRepository = Depends(get_chat_repo)) -> GetMessagesUseCase:
    return GetMessagesUseCase(repo)

def get_send_message_uc(repo: ChatRepository = Depends(get_chat_repo)) -> SendMessageUseCase:
    return SendMessageUseCase(repo)

def get_mark_read_uc(repo: ChatRepository = Depends(get_chat_repo)) -> MarkReadUseCase:
    return MarkReadUseCase(repo)

def get_group_message_uc(repo: ChatRepository = Depends(get_chat_repo)) -> SendGroupMessageUseCase:
    return SendGroupMessageUseCase(repo)

def get_group_messages_uc(repo: ChatRepository = Depends(get_chat_repo)) -> GetGroupMessagesUseCase:
    return GetGroupMessagesUseCase(repo)

def get_personal_deal_uc(repo: ChatRepository = Depends(get_chat_repo)) -> CreatePersonalDealUseCase:
    return CreatePersonalDealUseCase(repo)

def get_delete_message_uc(repo: ChatRepository = Depends(get_chat_repo)) -> DeleteMessageUseCase:
    return DeleteMessageUseCase(repo)

def get_share_recipients_uc(repo: ChatRepository = Depends(get_chat_repo)) -> GetShareRecipientsUseCase:
    return GetShareRecipientsUseCase(repo)

def get_all_chats_sorted(repo: ChatRepository = Depends(get_chat_repo)) -> GetAllChatsUseCase:
    return GetAllChatsUseCase(repo)

def get_group_conversations_uc(repo: ChatRepository = Depends(get_chat_repo)) -> GetGroupConversationsUseCase:
    return GetGroupConversationsUseCase(repo)


# ── Socket.IO wiring ─────────────────────────────────────────────────────────
# Sockets have no FastAPI request scope, so they cannot use Depends(). This is
# the same composition step done by hand, with a session the caller owns.

@dataclass
class SocketUseCases:
    can_join: CanJoinGroupRoomUseCase
    relay_typing: RelayTypingUseCase
    mark_delivered: MarkDeliveredUseCase


def build_socket_use_cases(db: Session) -> SocketUseCases:
    repo = ChatRepository(db)
    return SocketUseCases(
        can_join=CanJoinGroupRoomUseCase(repo),
        relay_typing=RelayTypingUseCase(repo),
        mark_delivered=MarkDeliveredUseCase(repo),
    )


def get_open_conversation_uc(repo: ChatRepository = Depends(get_chat_repo)) -> OpenConversationUseCase:
    return OpenConversationUseCase(repo)


def get_conversation_peer_uc(repo: ChatRepository = Depends(get_chat_repo)) -> GetConversationPeerUseCase:
    return GetConversationPeerUseCase(repo)


def get_deliver_shared_content_uc(
    repo: ChatRepository = Depends(get_chat_repo),
) -> DeliverSharedContentUseCase:
    """Post and news share flows deliver through chat, not into it."""
    return DeliverSharedContentUseCase(repo)
