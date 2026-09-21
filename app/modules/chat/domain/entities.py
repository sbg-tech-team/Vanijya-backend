# entities.py defines what things ARE in pure Python. No database. No HTTP. Just shapes of data that the rest of the codebase agrees on.

# The domain/ folder should be able to run with nothing installed except Python itself.

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
from uuid import UUID


# ── Conversation ───────────────────────────────────────────────────────────────

@dataclass
class UserSnap:
    """Minimal user profile needed inside the chat module."""
    user_id: UUID
    profile_id: int
    name: str
    is_user_verified: bool
    is_business_verified: bool
    avatar_url: Optional[str]
    role: str
    is_online: bool


@dataclass
class DMLastMessage:
    """Preview of the most recent message in a DM conversation."""
    id: UUID
    body: Optional[str]
    message_type: str
    sender_id: UUID
    sent_at: datetime


@dataclass
class GroupLastMessage:
    """Preview of the most recent message in a group conversation."""
    id: UUID
    sender_id: UUID
    sender_name: str
    body: Optional[str]
    message_type: str
    sent_at: datetime


@dataclass
class ConversationEntity:
    """A 1-to-1 DM conversation as seen in the inbox list."""
    id: UUID
    status: str  # ConversationStatus values
    initiator_id: Optional[UUID]
    participant: UserSnap
    last_message: Optional[DMLastMessage]
    unread_count: int
    is_muted: bool
    created_at: datetime
    updated_at: datetime


@dataclass
class ConversationMemberEntity:
    """Membership record linking a user to a conversation."""
    conversation_id: UUID
    user_id: UUID
    last_read_at: Optional[datetime]
    last_delivered_at: Optional[datetime]
    is_muted: bool
    joined_at: datetime


@dataclass
class GroupConversationEntity:
    """A group conversation as seen in the inbox list."""
    id: UUID
    group_name: str
    group_avatar: Optional[str]
    member_count: int
    last_message: Optional[GroupLastMessage]
    unread_count: int
    is_muted: bool
    created_at: datetime
    updated_at: datetime


# ── Deals and Posts ────────────────────────────────────────────────────────────

@dataclass
class PostSnap:
    """Lightweight post preview attached to a shared message."""
    post_id: int
    title: str
    image_urls: Optional[List[str]]
    caption: str
    category_id: int
    category_name: str
    author_name: str


@dataclass
class CallSnap:
    """Finished-call card. Written by the calling module when a call ends, so the
    call renders inline in the conversation the way WhatsApp does it.

    No `direction` field: the message's `sender` is the call initiator, so the
    client derives outgoing/incoming by comparing it to its own user_id — the
    same row is outgoing for one viewer and incoming for the other.
    """
    call_id: str
    media: str
    status: str
    end_reason: Optional[str]
    duration_seconds: int


@dataclass
class DealSnap:
    """Lightweight deal preview attached to a message."""
    deal_id: UUID
    title: str
    commodity_name: str
    grain_type: str
    grain_size: str
    commodity_quantity: float
    quantity_unit: str
    commodity_price: float
    price_type: str
    image_urls: Optional[List[str]]
    is_closed: bool
    caption: str


# ── Message ────────────────────────────────────────────────────────────────────

@dataclass
class ChatAttachmentEntity:
    """A single media attachment belonging to a message."""
    id: UUID
    message_id: UUID
    context_type: str
    context_id: UUID
    media_type: str
    media_url: str
    storage_path: Optional[str]
    created_at: datetime


@dataclass
class MessageEntity:
    """A single chat message — DM or group."""
    id: UUID
    context_id: UUID
    context_type: str
    sender: UserSnap
    message_type: str
    body: Optional[str]
    media_urls: Optional[List[str]]
    media_metadata: Optional[dict]
    location_lat: Optional[float]
    location_lon: Optional[float]
    reply_to_id: Optional[UUID]
    is_deleted: bool
    sent_at: datetime
    deal: Optional[DealSnap]
    post: Optional[PostSnap]
    attachments: List[ChatAttachmentEntity] = field(default_factory=list)
    # Present only when message_type == "call" — the finished-call card the
    # calling module writes into the thread. Built from media_metadata.
    call: Optional["CallSnap"] = None
    # Receipt ticks (DM only; None for group messages).
    # delivered = peer.last_delivered_at >= sent_at
    # read      = peer.last_read_at      >= sent_at
    delivered: Optional[bool] = None
    read: Optional[bool] = None
    # Filled only when the reader has continuous translation on for this
    # conversation AND a translation for their language already exists. Null
    # otherwise — the client falls back to `body`.
    translated_text: Optional[str] = None
    target_lang: Optional[str] = None


# ── Send guard ─────────────────────────────────────────────────────────────────

@dataclass
class ConvSendGuard:
    """Lightweight result from get_conv_send_info — only what send_message needs."""
    status: str
    initiator_id: Optional[UUID]
    receiver_id: UUID
    sender_snap: UserSnap


# ── Share recipients ───────────────────────────────────────────────────────────

@dataclass
class ShareDMItem:
    """One active DM connection the current user can forward a message to."""
    conversation_id: UUID
    profile_id: int
    user_id: UUID
    name: str
    avatar_url: Optional[str]
    last_message_at: Optional[datetime]


@dataclass
class ShareGroupItem:
    """One group the current user belongs to (unfrozen). can_send reflects chat_perm + role."""
    group_id: UUID
    name: str
    avatar_url: Optional[str]
    member_count: int
    can_send: bool


@dataclass
class ShareRecipientsResult:
    dm_connections: List[ShareDMItem]
    groups: List[ShareGroupItem]


# ── Unified chat list ──────────────────────────────────────────────────────────

@dataclass
class ChatListItem:
    """One row in the combined 'all chats' inbox — exactly one of dm/group is set."""
    type: str                            # "dm" | "group"
    last_activity: datetime              # sort key — newest first
    dm: Optional[ConversationEntity] = None
    group: Optional[GroupConversationEntity] = None
