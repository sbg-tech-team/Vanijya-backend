"""
Value objects and enums for the connections domain.
Pure Python — no SQLAlchemy, FastAPI, Pydantic, or Redis imports.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class MessageRequestStatus(str, Enum):
    """Lifecycle states of a MessageRequest."""
    PENDING  = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"


class UserRole(str, Enum):
    """Business roles a user can hold on the platform."""
    TRADER   = "trader"
    BROKER   = "broker"
    EXPORTER = "exporter"


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class QuantityRange:
    """
    Minimum and maximum trade quantity in metric tonnes.
    Both bounds are non-negative integers.
    """
    min_mt: int
    max_mt: int

    def __post_init__(self) -> None:
        if self.min_mt < 0:
            raise ValueError("min_mt must be >= 0")
        if self.max_mt < self.min_mt:
            raise ValueError("max_mt must be >= min_mt")

    def __str__(self) -> str:
        return f"{self.min_mt}–{self.max_mt}mt"


@dataclass(frozen=True)
class GeoLocation:
    """
    Geographic coordinates (decimal degrees).
    latitude  : -90.0 to +90.0
    longitude : -180.0 to +180.0
    """
    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if not (-90.0 <= self.latitude <= 90.0):
            raise ValueError(f"Invalid latitude: {self.latitude}")
        if not (-180.0 <= self.longitude <= 180.0):
            raise ValueError(f"Invalid longitude: {self.longitude}")


@dataclass(frozen=True)
class SearchIntent:
    """
    Structured result of parsing a free-text search query.
    Fields that could not be extracted are None.
    """
    role: str | None      # UserRole value or None
    commodity: str | None
    city: str | None
    name_q: str | None    # residual tokens treated as a name search


@dataclass(frozen=True)
class ConnectionPair:
    """
    An ordered (follower, following) pair that uniquely identifies a follow edge.
    Composite primary key in the follow graph.
    """
    follower_id: object    # UUID — kept as `object` to stay stdlib-only
    following_id: object   # UUID

    def __post_init__(self) -> None:
        if self.follower_id == self.following_id:
            raise ValueError("A user cannot follow themselves.")
