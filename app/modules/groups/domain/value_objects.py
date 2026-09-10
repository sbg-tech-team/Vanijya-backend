"""
Value objects and enums for the Groups domain.
Pure Python — no SQLAlchemy, FastAPI, Pydantic, or Redis imports.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


# ---------------------------------------------------------------------------
# Enums derived from string-choice columns in the SQLAlchemy models
# ---------------------------------------------------------------------------

class GroupAccessibility(str, Enum):
    """Controls who can discover and join the group."""
    PUBLIC = "public"
    PRIVATE = "private"
    INVITE_ONLY = "invite_only"


class GroupPostingPerm(str, Enum):
    """Controls who can post deals/messages in the group."""
    ALL_MEMBERS = "all_members"
    ADMINS_ONLY = "admins_only"


class GroupChatPerm(str, Enum):
    """Controls who can send chat messages in the group."""
    ALL_MEMBERS = "all_members"
    ADMINS_ONLY = "admins_only"


class GroupCategory(str, Enum):
    """Broad purpose category of the group."""
    COMMODITY_TRADING = "commodity_trading"
    NEWS = "news"
    NETWORK = "network"


class GroupMemberRole(str, Enum):
    """Role of a user within a specific group."""
    ADMIN = "admin"
    MEMBER = "member"


class JoinRequestStatus(str, Enum):
    """Lifecycle state of a GroupJoinRequest."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class DealPriceType(str, Enum):
    """Whether a deal price is fixed or open to negotiation."""
    FIXED = "fixed"
    NEGOTIABLE = "negotiable"


class DealQuantityUnit(str, Enum):
    """Unit of measure for commodity quantity in a deal."""
    MT = "MT"
    QUINTAL = "quintal"


class GroupMediaType(str, Enum):
    """Category of a media file uploaded to a group."""
    IMAGE = "image"
    VIDEO = "video"


class TargetRole(str, Enum):
    """Trading roles that a group may target."""
    TRADER = "trader"
    BROKER = "broker"
    EXPORTER = "exporter"


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GeoLocation:
    """Immutable geographic coordinate pair."""
    lat: float
    lon: float

    def __post_init__(self) -> None:
        if not (-90.0 <= self.lat <= 90.0):
            raise ValueError(f"Latitude must be between -90 and 90, got {self.lat}")
        if not (-180.0 <= self.lon <= 180.0):
            raise ValueError(f"Longitude must be between -180 and 180, got {self.lon}")


@dataclass(frozen=True)
class RegionMarket:
    """Named market / region used for filtering and display."""
    name: str
    location: GeoLocation | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("Region market name must not be empty")


@dataclass(frozen=True)
class InviteToken:
    """Opaque invite-link token with a stable URL representation."""
    token: str

    def join_url(self, base_url: str = "https://api.vanijyaa.com") -> str:
        return f"{base_url}/api/v1/groups/join-by-link/{self.token}"


@dataclass(frozen=True)
class DealPrice:
    """Price + unit together form a meaningful value object for a deal."""
    amount: float
    price_type: DealPriceType

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise ValueError("Deal price cannot be negative")


@dataclass(frozen=True)
class DealQuantity:
    """Quantity + unit together form a meaningful value object for a deal."""
    amount: float
    unit: DealQuantityUnit

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError("Deal quantity must be greater than zero")


@dataclass(frozen=True)
class GroupPermissions:
    """Encapsulates all three permission axes of a group in one object."""
    accessibility: GroupAccessibility = GroupAccessibility.PUBLIC
    posting_perm: GroupPostingPerm = GroupPostingPerm.ALL_MEMBERS
    chat_perm: GroupChatPerm = GroupChatPerm.ALL_MEMBERS
