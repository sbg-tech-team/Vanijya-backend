"""
Domain entities for the profile module.
Pure Python — no SQLAlchemy, FastAPI, Pydantic, or Redis imports.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID


# ---------------------------------------------------------------------------
# Lookup / reference entities
# ---------------------------------------------------------------------------

@dataclass
class RoleEntity:
    id: int                          # 1=Trader  2=Broker  3=Exporter
    name: str
    # description: Optional[str] = None


@dataclass
class CommodityEntity:
    id: int                          # 1=Rice  2=Cotton  3=Sugar
    name: str


@dataclass
class InterestEntity:
    id: int                          # 1=Connections  2=Leads  3=News
    name: str


# ---------------------------------------------------------------------------
# Junction / association entities
# ---------------------------------------------------------------------------

@dataclass
class ProfileCommodityEntity:
    id: int
    profile_id: int
    commodity_id: int
    commodity: Optional[CommodityEntity] = None


@dataclass
class ProfileInterestEntity:
    id: int
    profile_id: int
    interest_id: int
    interest: Optional[InterestEntity] = None


# ---------------------------------------------------------------------------
# Business (location info — 1:1 with Profile)
# ---------------------------------------------------------------------------

@dataclass
class BusinessEntity:
    id: int
    profile_id: int
    latitude: float
    longitude: float
    business_name: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@dataclass
class ProfileEntity:
    id: int
    users_id: UUID
    role_id: int
    name: str
    quantity_min: Decimal
    quantity_max: Decimal
    is_user_verified: bool = False
    is_business_verified: bool = False
    followers_count: int = 0
    following_count: int = 0
    avatar_url: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # Relationships
    user: Optional["UserEntity"] = None
    business: Optional[BusinessEntity] = None
    commodities: List[ProfileCommodityEntity] = field(default_factory=list)
    interests: List[ProfileInterestEntity] = field(default_factory=list)


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

@dataclass
class UserEntity:
    id: UUID
    country_code: str
    phone_number: str
    is_active: bool = True
    created_at: Optional[datetime] = None
    fcm_token: Optional[str] = None
    access_token: Optional[str] = None

    # Relationship
    profile: Optional[ProfileEntity] = None


# ---------------------------------------------------------------------------
# User embedding (IS vector + post feed vector)
# ---------------------------------------------------------------------------

@dataclass
class UserEmbeddingEntity:
    user_id: UUID
    updated_at: Optional[datetime] = None
    # 11-dim IS vector  [3 commodity | 3 role | 3 geo | 2 qty]
    is_vector: Optional[List[float]] = None
    # 10-dim post feed vector
    post_feed_vector: Optional[List[float]] = None


@dataclass
class NotificationPrefs:
    """What a user has switched on. All True is the default for anyone who has
    never opened Settings — there is no row for them and none is created until
    they change something."""
    push_enabled: bool = True
    market_alerts_enabled: bool = True
    group_enabled: bool = True
