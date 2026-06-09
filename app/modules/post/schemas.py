from datetime import datetime, timezone
from typing import Optional, List

from pydantic import BaseModel, computed_field, field_validator, model_validator


def _time_elapsed(dt: datetime) -> str:
    now = datetime.now(timezone.utc)
    aware = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    seconds = max(0, int((now - aware).total_seconds()))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        m = seconds // 60
        return f"{m} minute{'s' if m != 1 else ''} ago"
    if seconds < 86400:
        h = seconds // 3600
        return f"{h} hour{'s' if h != 1 else ''} ago"
    if seconds < 604800:
        d = seconds // 86400
        return f"{d} day{'s' if d != 1 else ''} ago"
    if seconds < 2592000:
        w = seconds // 604800
        return f"{w} week{'s' if w != 1 else ''} ago"
    mo = seconds // 2592000
    return f"{mo} month{'s' if mo != 1 else ''} ago"

# Fixed category IDs (matches DB seed)
CATEGORY_DEAL = 4

VALID_PRICE_TYPES = {"fixed", "negotiable"}
VALID_QUANTITY_UNITS = {"MT", "quintal"}


# ----------------------------------------------------------------------------
# Deal / Requirement nested schemas
# ----------------------------------------------------------------------------

class PostDealCreate(BaseModel):
    grain_type: str
    grain_size: str
    commodity_quantity: float
    quantity_unit: str
    commodity_price: float
    price_type: str  # fixed | negotiable

    @field_validator("price_type")
    @classmethod
    def price_type_valid(cls, v: str) -> str:
        if v not in VALID_PRICE_TYPES:
            raise ValueError(f"price_type must be one of: {', '.join(VALID_PRICE_TYPES)}")
        return v

    @field_validator("quantity_unit")
    @classmethod
    def quantity_unit_valid(cls, v: str) -> str:
        if v not in VALID_QUANTITY_UNITS:
            raise ValueError(f"quantity_unit must be one of: {', '.join(VALID_QUANTITY_UNITS)}")
        return v


class PostDealUpdate(BaseModel):
    grain_type: Optional[str] = None
    grain_size: Optional[str] = None
    commodity_quantity: Optional[float] = None
    quantity_unit: Optional[str] = None
    commodity_price: Optional[float] = None
    price_type: Optional[str] = None

    @field_validator("price_type")
    @classmethod
    def price_type_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_PRICE_TYPES:
            raise ValueError(f"price_type must be one of: {', '.join(VALID_PRICE_TYPES)}")
        return v

    @field_validator("quantity_unit")
    @classmethod
    def quantity_unit_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_QUANTITY_UNITS:
            raise ValueError(f"quantity_unit must be one of: {', '.join(VALID_QUANTITY_UNITS)}")
        return v


class PostDealResponse(BaseModel):
    grain_type: str
    grain_size: str
    commodity_quantity: float
    quantity_unit: str
    commodity_price: float
    price_type: str
    is_closed: bool

    class Config:
        from_attributes = True


# ----------------------------------------------------------------------------
# Post create / update
# ----------------------------------------------------------------------------

class PostCreate(BaseModel):
    # Required
    category_id: int        # 1=Market Update 2=Knowledge 3=Discussion 4=Deal/Requirement
    commodity_id: int       # 1=Rice 2=Cotton 3=Sugar
    title: str
    caption: str

    # Visibility
    is_public: bool = True                      # True=all users, False=followers only
    target_roles: Optional[List[int]] = None    # null=all roles, [1/2/3]=specific roles

    # Interaction
    allow_comments: bool = True

    # Optional media (up to 5 URLs)
    image_urls: Optional[List[str]] = None

    @field_validator("image_urls")
    @classmethod
    def image_urls_max_five(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None and len(v) > 5:
            raise ValueError("A post can have at most 5 images")
        return v or None

    # Optional metadata
    source_url: Optional[str] = None       # link to information source
    location_name: Optional[str] = None    # human-readable place name
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # Deal / Requirement (required when category_id == 4)
    deal_details: Optional[PostDealCreate] = None

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Title cannot be empty")
        return v.strip()

    @field_validator("caption")
    @classmethod
    def caption_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Caption cannot be empty")
        return v.strip()

    @model_validator(mode="after")
    def validate_category_fields(self) -> "PostCreate":
        if self.category_id == CATEGORY_DEAL and not self.deal_details:
            raise ValueError("deal_details is required for Deal/Requirement posts")
        return self


# ----------------------------------------------------------------------------
# Post update (PATCH – all fields optional)
# ----------------------------------------------------------------------------

class PostUpdate(BaseModel):
    title: Optional[str] = None
    caption: Optional[str] = None
    image_urls: Optional[List[str]] = None
    source_url: Optional[str] = None
    location_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_public: Optional[bool] = None
    target_roles: Optional[List[int]] = None
    allow_comments: Optional[bool] = None
    deal_details: Optional[PostDealUpdate] = None

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("Title cannot be empty")
        return v.strip() if v else v

    @field_validator("caption")
    @classmethod
    def caption_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("Caption cannot be empty")
        return v.strip() if v else v


# ----------------------------------------------------------------------------
# Post response
# ----------------------------------------------------------------------------

class PostResponse(BaseModel):
    id: int
    profile_id: int
    category_id: int
    commodity_id: int
    title: str
    caption: str
    image_urls: Optional[List[str]]
    is_public: bool
    target_roles: Optional[List[int]]
    allow_comments: bool

    deal_details: Optional[PostDealResponse]

    source_url: Optional[str]
    location_name: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]

    # Counters + viewer state
    view_count: int
    like_count: int
    comment_count: int
    share_count: int
    save_count: int
    is_liked: bool
    is_saved: bool

    created_at: datetime

    @computed_field
    @property
    def time_elapsed(self) -> str:
        return _time_elapsed(self.created_at)

    class Config:
        from_attributes = True


# ----------------------------------------------------------------------------
# Following feed
# ----------------------------------------------------------------------------

class FollowingFeedResponse(BaseModel):
    posts: List[PostResponse]
    all_caught_up: bool
    next_cursor: Optional[int] = None  # last post_id in this page; None = end of feed


# ----------------------------------------------------------------------------
# Comments
# ----------------------------------------------------------------------------

class CommentCreate(BaseModel):
    content: str

    @field_validator("content")
    @classmethod
    def content_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Comment content cannot be empty")
        return v.strip()


class CommentResponse(BaseModel):
    id: int
    post_id: int
    profile_id: int
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


# ----------------------------------------------------------------------------
# Interaction responses
# ----------------------------------------------------------------------------

class LikeResponse(BaseModel):
    liked: bool
    like_count: int


class SaveResponse(BaseModel):
    saved: bool


class ShareResponse(BaseModel):
    share_count: int


class DealClosedResponse(BaseModel):
    is_closed: bool
