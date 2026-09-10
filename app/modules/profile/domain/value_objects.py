"""
Value objects and enums for the profile domain.
Pure Python — no SQLAlchemy, FastAPI, Pydantic, or Redis imports.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import IntEnum, Enum


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class RoleEnum(IntEnum):
    """Maps role_id integer to its business meaning."""
    TRADER = 1
    BROKER = 2
    EXPORTER = 3

    @property
    def label(self) -> str:
        return self.name.capitalize()

    @classmethod
    def name_for(cls, role_id: int) -> str:
        """Return the lowercase role name used by the vector encoder."""
        return cls(role_id).name.lower()


class CommodityEnum(IntEnum):
    """Seed commodity IDs — extend as the lookup table grows."""
    RICE = 1
    COTTON = 2
    SUGAR = 3


class InterestEnum(IntEnum):
    """Seed interest IDs — extend as the lookup table grows."""
    CONNECTIONS = 1
    LEADS = 2
    NEWS = 3


class ImageContentType(str, Enum):
    """Allowed MIME types for avatar uploads."""
    JPEG = "image/jpeg"
    PNG = "image/png"
    WEBP = "image/webp"


# ---------------------------------------------------------------------------
# Value objects — immutable, equality-by-value, no identity/DB columns
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PhoneNumber:
    """A validated E.164-style phone number split into its two parts."""
    country_code: str   # e.g. "+91"
    number: str         # digits only, e.g. "9876543210"

    def __post_init__(self) -> None:
        if not self.country_code:
            raise ValueError("country_code must not be empty")
        if not self.number.isdigit():
            raise ValueError("phone number must contain only digits")
        if not (5 <= len(self.number) <= 15):
            raise ValueError("phone number length must be between 5 and 15 digits")

    def __str__(self) -> str:
        return f"{self.country_code}{self.number}"


@dataclass(frozen=True)
class Location:
    """Geographic coordinates with optional human-readable labels."""
    latitude: float
    longitude: float
    city: str | None = None
    state: str | None = None

    def __post_init__(self) -> None:
        if not (-90.0 <= self.latitude <= 90.0):
            raise ValueError(f"Invalid latitude: {self.latitude}")
        if not (-180.0 <= self.longitude <= 180.0):
            raise ValueError(f"Invalid longitude: {self.longitude}")


@dataclass(frozen=True)
class QuantityRange:
    """Min/max commodity quantity a trader deals in (in metric tonnes or agreed unit)."""
    minimum: Decimal
    maximum: Decimal

    def __post_init__(self) -> None:
        if self.minimum < Decimal(0):
            raise ValueError("quantity_min must be non-negative")
        if self.maximum < self.minimum:
            raise ValueError("quantity_min cannot be greater than quantity_max")


@dataclass(frozen=True)
class AvatarUrl:
    """A validated avatar URL that belongs to the avatars storage bucket."""
    url: str

    def __post_init__(self) -> None:
        if not self.url.startswith("http"):
            raise ValueError("avatar_url must be a valid HTTP(S) URL")

    def __str__(self) -> str:
        return self.url
