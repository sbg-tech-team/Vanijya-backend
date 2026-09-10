from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class PostDealDetails:
    id: int
    post_id: int
    grain_type: str
    grain_size: str
    commodity_quantity: float
    quantity_unit: str
    commodity_price: float
    price_type: str
    is_closed: bool = False


@dataclass
class PostView:
    id: int
    post_id: int
    profile_id: int
    viewed_at: datetime


@dataclass
class PostLike:
    id: int
    post_id: int
    profile_id: int
    liked_at: datetime


@dataclass
class PostComment:
    id: int
    post_id: int
    profile_id: int
    content: str
    created_at: datetime


@dataclass
class PostShare:
    id: int
    post_id: int
    profile_id: int
    shared_at: datetime


@dataclass
class PostSave:
    id: int
    post_id: int
    profile_id: int
    saved_at: datetime


@dataclass
class PostCategory:
    id: int
    name: str


@dataclass
class Post:
    id: int
    profile_id: int
    category_id: int
    commodity_id: int
    title: str
    caption: str
    is_public: bool
    allow_comments: bool
    like_count: int
    view_count: int
    comment_count: int
    share_count: int
    save_count: int
    created_at: datetime

    image_urls: Optional[List[str]] = None
    source_url: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_name: Optional[str] = None
    target_roles: Optional[List[int]] = None

    deal_details: Optional[PostDealDetails] = None
    views: List[PostView] = field(default_factory=list)
    likes: List[PostLike] = field(default_factory=list)
    comments: List[PostComment] = field(default_factory=list)
    shares: List[PostShare] = field(default_factory=list)
    saves: List[PostSave] = field(default_factory=list)
