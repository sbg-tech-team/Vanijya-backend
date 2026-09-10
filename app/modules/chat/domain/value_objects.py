# value_objects.py — enums and small immutable value types for the chat domain.
# Pure Python only: no SQLAlchemy, no FastAPI, no Pydantic, no Redis.

from dataclasses import dataclass
from enum import Enum
from typing import Optional


# ── Conversation ───────────────────────────────────────────────────────────────

class ConversationStatus(str, Enum):
    """Lifecycle state of a 1-to-1 DM conversation."""
    REQUESTED = "requested"
    ACTIVE = "active"
    BLOCKED = "blocked"


class ConversationType(str, Enum):
    """Whether the conversation is a direct message or a group thread."""
    DM = "dm"
    GROUP = "group"


# ── Message ────────────────────────────────────────────────────────────────────

class MessageType(str, Enum):
    """Payload kind carried by a Message row."""
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    LOCATION = "location"
    DEAL = "deal"
    POST = "post"


class ContextType(str, Enum):
    """Which chat surface a message belongs to."""
    DM = "dm"
    GROUP = "group"


# ── Media / attachment ─────────────────────────────────────────────────────────

class MediaType(str, Enum):
    """Broad category of an attachment stored in chat_attachments."""
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"


# ── Deal ──────────────────────────────────────────────────────────────────────

class PriceType(str, Enum):
    FIXED = "fixed"
    NEGOTIABLE = "negotiable"


class QuantityUnit(str, Enum):
    MT = "MT"
    QUINTAL = "quintal"


# ── Post ──────────────────────────────────────────────────────────────────────

class PostCategory(str, Enum):
    MARKET_UPDATE = "Market Update"
    KNOWLEDGE = "Knowledge"
    DISCUSSION = "Discussion"
    DEAL_REQ = "Deal/Requirements"


# ── Value-object dataclasses ───────────────────────────────────────────────────

@dataclass(frozen=True)
class GeoLocation:
    """An immutable GPS coordinate pair attached to a location message."""
    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if not (-90.0 <= self.latitude <= 90.0):
            raise ValueError(f"Invalid latitude: {self.latitude}")
        if not (-180.0 <= self.longitude <= 180.0):
            raise ValueError(f"Invalid longitude: {self.longitude}")


@dataclass(frozen=True)
class MediaUploadResult:
    """Returned after requesting a signed upload URL for chat media."""
    upload_url: str
    media_url: str
    storage_path: str
    content_type: str


@dataclass(frozen=True)
class MessageReceipt:
    """Delivery/read receipt state for a single DM message (sender's perspective)."""
    delivered: Optional[bool]
    read: Optional[bool]
