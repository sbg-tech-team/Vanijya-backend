"""
Domain entities for the Groups module.
Pure Python — no SQLAlchemy, FastAPI, Pydantic, or Redis imports.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
from uuid import UUID


@dataclass
class GroupActivityCache:
    group_id: UUID
    messages_24h: int = 0
    unique_senders_24h: int = 0
    active_members_7d: int = 0
    member_growth_7d: int = 0
    updated_at: Optional[datetime] = None


@dataclass
class GroupEmbedding:
    """11-dim IS vector for ANN group recommendation."""
    group_id: UUID
    # Layout: [3 commodity | 3 role | 3 geo | 2 zeros]
    embedding: Optional[List[float]] = None
    updated_at: Optional[datetime] = None


@dataclass
class GroupMedia:
    id: UUID
    group_id: UUID
    uploaded_by: UUID
    media_url: str
    media_type: str          # "image" | "video"
    storage_path: str
    uploaded_at: Optional[datetime] = None


@dataclass
class GroupMember:
    group_id: UUID
    user_id: UUID
    role: str = "member"     # "admin" | "member"
    is_frozen: bool = False
    is_muted: bool = False
    is_favorite: bool = False
    joined_at: Optional[datetime] = None


@dataclass
class Group:
    id: UUID
    name: str
    created_by: UUID
    description: Optional[str] = None
    group_rules: Optional[str] = None
    image_url: Optional[str] = None

    # Lists of commodity names and role names
    commodity: List[str] = field(default_factory=list)
    target_roles: List[str] = field(default_factory=list)

    region_lat: Optional[float] = None
    region_lon: Optional[float] = None
    region_market: Optional[str] = None

    # "commodity_trading" | "news" | "network"
    category: Optional[str] = None

    # "public" | "private" | "invite_only"
    accessibility: str = "public"
    # "all_members" | "admins_only"
    posting_perm: str = "all_members"
    chat_perm: str = "all_members"

    invite_link_token: Optional[str] = None
    member_count: int = 1
    created_at: Optional[datetime] = None

    # Aggregated relationships (populated on demand)
    members: List[GroupMember] = field(default_factory=list)
    activity_cache: Optional[GroupActivityCache] = None
    embedding: Optional[GroupEmbedding] = None
    media: List[GroupMedia] = field(default_factory=list)


@dataclass
class GroupDeal:
    id: UUID
    group_id: UUID
    posted_by: UUID
    commodity_id: int
    title: str
    caption: str
    grain_type: str
    grain_size: str
    commodity_quantity: float
    quantity_unit: str       # "MT" | "quintal"
    commodity_price: float
    price_type: str          # "fixed" | "negotiable"
    image_urls: Optional[List[str]] = None
    is_closed: bool = False
    # None until the author promotes the deal to the public feed
    post_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class GroupJoinRequest:
    id: UUID
    group_id: UUID
    user_id: UUID
    # "pending" | "approved" | "rejected"
    status: str = "pending"
    created_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[UUID] = None


@dataclass
class PersonalDeal:
    id: UUID
    conversation_id: UUID
    posted_by: UUID
    commodity_id: int
    title: str
    caption: str
    grain_type: str
    grain_size: str
    commodity_quantity: float
    quantity_unit: str       # "MT" | "quintal"
    commodity_price: float
    price_type: str          # "fixed" | "negotiable"
    image_urls: Optional[List[str]] = None
    is_closed: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
