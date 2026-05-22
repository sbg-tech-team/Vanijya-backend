from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID


@dataclass
class UserSnap:
    user_id: UUID
    profile_id: int
    name: str
    is_user_verified: bool
    is_business_verified: bool


@dataclass
class LastMessage:
    id: UUID
    body: Optional[str]
    message_type: str
    sender_id: UUID
    sent_at: datetime


@dataclass
class ConversationEntity:
    id: UUID
    status: str
    initiator_id: Optional[UUID]
    participant: UserSnap
    last_message: Optional[LastMessage]
    unread_count: int
    is_muted: bool
    created_at: datetime
    updated_at: datetime


@dataclass
class MessageEntity:
    id: UUID
    context_id: UUID
    context_type: str
    sender: UserSnap
    message_type: str
    body: Optional[str]
    media_url: Optional[str]
    media_metadata: Optional[dict]
    location_lat: Optional[float]
    location_lon: Optional[float]
    reply_to_id: Optional[UUID]
    is_deleted: bool
    sent_at: datetime


class ConvStatus:
    REQUESTED = "requested"
    ACTIVE    = "active"
    BLOCKED   = "blocked"


@dataclass
class ConvSendGuard:
    """Lightweight result from get_conv_send_info — only what send_message needs."""
    status: str
    initiator_id: Optional[UUID]
    receiver_id: UUID
    sender_snap: UserSnap
