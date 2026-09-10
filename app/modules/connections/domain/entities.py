"""
Domain entities for the connections module.
Pure Python — no SQLAlchemy, FastAPI, Pydantic, or Redis imports.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
from uuid import UUID


@dataclass
class UserConnection:
    """
    Represents a directional follow edge between two users.
    follower_id  -> the user who clicked "follow"
    following_id -> the user being followed
    """
    follower_id: UUID
    following_id: UUID
    followed_at: datetime


@dataclass
class MessageRequest:
    """
    One-directional message request from sender to receiver.
    A single open channel per (sender, receiver) pair at a time.
    status: pending | accepted | declined
    """
    id: int
    sender_id: UUID
    receiver_id: UUID
    status: str
    sent_at: datetime
    first_message: Optional[str] = None
    acted_at: Optional[datetime] = None


@dataclass
class UserProfile:
    """
    Lightweight projection of a user's profile as needed by the connections domain.
    Aggregates fields from Profile, Business, Role, and Commodity.
    """
    user_id: UUID
    name: str
    avatar_url: Optional[str]
    role: Optional[str]                # trader | broker | exporter
    commodities: List[str] = field(default_factory=list)
    is_user_verified: bool = False
    is_business_verified: bool = False
    quantity_min: int = 0
    quantity_max: int = 0
    business_name: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None


@dataclass
class ConnectionStatus:
    """
    Snapshot of the relationship between the calling user (me) and a target user.
    Used to drive UI state (follow button, message-request badge, etc.).
    """
    target_user_id: UUID
    follow_status: bool = False
    msg_req_status: Optional[str] = None   # None | pending | accepted | declined


@dataclass
class RecommendationResult:
    """
    A single entry returned by the vector-based recommendation engine.
    Wraps a UserProfile with its cosine-similarity score.
    """
    profile: UserProfile
    similarity: float
    msg_req_status: Optional[str] = None
    follow_status: bool = False


@dataclass
class ReceivedRequest:
    """
    An incoming message request as seen by the receiver.
    """
    request_id: int
    sender_profile: UserProfile
    first_message: Optional[str]
    sent_at: datetime


@dataclass
class SentRequest:
    """
    An outgoing message request as seen by the sender.
    """
    request_id: int
    receiver_profile: UserProfile
    status: str
    sent_at: datetime
    first_message: Optional[str] = None
    acted_at: Optional[datetime] = None
