from sqlalchemy.orm import Session
from fastapi import Depends
from app.modules.chat.data.repository import ChatRepository
from app.modules.chat.domain.use_cases import *
from app.dependencies import get_db

def get_chat_repo(db: Session = Depends(get_db)) -> ChatRepository:
    return ChatRepository(db)

def get_conversations_uc(repo: ChatRepository = Depends(get_chat_repo)) -> GetConversationsUseCase:
    return GetConversationsUseCase(repo)

def get_open_chat_uc(repo: ChatRepository = Depends(get_chat_repo)) -> OpenChatUseCase:
    return OpenChatUseCase(repo)

def get_messages_uc(repo: ChatRepository = Depends(get_chat_repo)) -> GetMessagesUseCase:
    return GetMessagesUseCase(repo)

def get_mark_read_uc(repo: ChatRepository = Depends(get_chat_repo)) -> MarkReadUseCase:
    return MarkReadUseCase(repo)

def get_accept_uc(repo: ChatRepository = Depends(get_chat_repo)) -> AcceptConversationUseCase:
    return AcceptConversationUseCase(repo)

def get_decline_uc(repo: ChatRepository = Depends(get_chat_repo)) -> DeclineConversationUseCase:
    return DeclineConversationUseCase(repo)

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