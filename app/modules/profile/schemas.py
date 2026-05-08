from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Reference data responses
# ---------------------------------------------------------------------------

class CommodityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class InterestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: Optional[str]


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

class UserCreate(BaseModel):
    phone_number: str
    country_code: str


class FcmTokenUpdate(BaseModel):
    fcm_token: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    phone_number: str
    country_code: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Profile — create (covers screens 3, 4, 5)
# ---------------------------------------------------------------------------

class ProfileCreate(BaseModel):
    # Screen 3
    role_id: int                    # 1=Trader  2=Broker  3=Exporter

    # Screen 4
    name: str
    commodities: List[int]          # [1=Rice, 2=Cotton, 3=Sugar] — multi-select
    interests: List[int]            # [1=Connections, 2=Leads, 3=News] — multi-select
    quantity_min: float
    quantity_max: float

    # Screen 5
    business_name: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    latitude: float
    longitude: float


# ---------------------------------------------------------------------------
# Profile — responses
# ---------------------------------------------------------------------------

class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    role_id: int
    phone_number: str       # from users table — shown as read-only on Edit Profile screen
    country_code: str
    commodities: List[CommodityOut]
    interests: List[InterestOut]
    is_verified: bool
    is_user_verified: bool
    is_business_verified: bool
    followers_count: int
    following_count: int
    posts_count: int
    business_name: Optional[str]
    city: Optional[str] = None
    state: Optional[str] = None
    latitude: float
    longitude: float
    avatar_url: Optional[str] = None


class ProfilePublicResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    role_id: int
    is_verified: bool
    commodities: List[CommodityOut]
    followers_count: int
    following_count: int
    posts_count: int
    business_name: Optional[str]
    city: Optional[str] = None
    state: Optional[str] = None
    latitude: float
    longitude: float
    avatar_url: Optional[str] = None


# ---------------------------------------------------------------------------
# Profile — update
# ---------------------------------------------------------------------------

class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    commodities: Optional[List[int]] = None
    interests: Optional[List[int]] = None
    quantity_min: Optional[float] = None
    quantity_max: Optional[float] = None
    business_name: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


# ---------------------------------------------------------------------------
# Profile verification — Screen 6 (optional)
# ---------------------------------------------------------------------------

VALID_IDENTITY_TYPES = {"pan_card", "aadhaar_card"}
VALID_BUSINESS_TYPES = {"gst_certificate", "trade_license"}


class DocumentSubmit(BaseModel):
    document_type: str    # pan_card | aadhaar_card | gst_certificate | trade_license
    document_number: str


class VerifyProfileRequest(BaseModel):
    identity_proof: Optional[DocumentSubmit] = None   # PAN or Aadhaar
    business_proof: Optional[DocumentSubmit] = None   # GST or Trade License
