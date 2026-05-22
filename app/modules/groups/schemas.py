from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class GroupCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=200)
    description: Optional[str] = None
    group_rules: Optional[str] = None
    commodities: Optional[List[str]] = Field(default_factory=list)
    region_market: Optional[str] = None
    region_lat: Optional[float] = None
    region_lon: Optional[float] = None
    # commodity_trading | news | network
    category: Optional[str] = None
    # public | private | invite_only
    accessibility: str = "public"
    # all_members | admins_only
    posting_perm: str = "all_members"
    chat_perm: str = "all_members"
    target_roles: Optional[List[str]] = Field(default_factory=list)
    initial_member_ids: Optional[List[UUID]] = Field(default_factory=list)


class GroupUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=3, max_length=200)
    description: Optional[str] = None
    group_rules: Optional[str] = None
    icon_url: Optional[str] = None
    commodities: Optional[List[str]] = None
    region_market: Optional[str] = None
    region_lat: Optional[float] = None
    region_lon: Optional[float] = None
    category: Optional[str] = None


class GroupPermissionsUpdate(BaseModel):
    accessibility: Optional[str] = None
    posting_perm: Optional[str] = None
    chat_perm: Optional[str] = None


class AddMembersRequest(BaseModel):
    user_ids: List[UUID]


class ReportGroupRequest(BaseModel):
    reason: str
    details: Optional[str] = None


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class GroupOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    icon_url: Optional[str] = None
    commodity: Optional[List[str]] = None
    target_roles: Optional[List[str]] = None
    region_market: Optional[str] = None
    region_lat: Optional[float] = None
    region_lon: Optional[float] = None
    category: Optional[str] = None
    accessibility: str
    posting_perm: str
    chat_perm: str
    member_count: int
    created_by: UUID
    created_at: datetime
    # current-user context (populated in service layer)
    is_member: bool = False
    member_role: Optional[str] = None
    is_muted: bool = False
    is_favorite: bool = False

    class Config:
        from_attributes = True


class GroupMemberOut(BaseModel):
    user_id: UUID
    name: str
    role: str               # Trader / Broker / Exporter
    avatar_url: Optional[str] = None
    is_admin: bool
    is_user_verified: bool
    is_business_verified: bool
    member_role: str        # admin | member
    is_frozen: bool
    is_muted: bool
    joined_at: datetime


class GroupSuggestionOut(BaseModel):
    group: GroupOut
    match_score: float
    match_reasons: List[str]


class InviteLinkOut(BaseModel):
    invite_link_token: str
    join_url: str


class GroupListOut(BaseModel):
    groups: List[GroupOut]
    total: int
    page: int
    per_page: int


class GroupMembersPageOut(BaseModel):
    members: List[GroupMemberOut]
    total: int
    page: int
    limit: int
