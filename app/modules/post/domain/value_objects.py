from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Optional


# ---------------------------------------------------------------------------
# Fixed category IDs (seeded in migration)
# ---------------------------------------------------------------------------

class PostCategoryId(IntEnum):
    MARKET_UPDATE = 1
    KNOWLEDGE = 2
    DISCUSSION = 3
    DEAL = 4


# ---------------------------------------------------------------------------
# Enums derived from string choices in the models
# ---------------------------------------------------------------------------

class QuantityUnit(str, Enum):
    MT = "MT"
    QUINTAL = "quintal"


class PriceType(str, Enum):
    FIXED = "fixed"
    NEGOTIABLE = "negotiable"


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Location:
    latitude: float
    longitude: float
    location_name: Optional[str] = None


@dataclass(frozen=True)
class DealSpec:
    """Immutable value object capturing the commercial terms of a Deal post."""
    grain_type: str
    grain_size: str
    commodity_quantity: float
    quantity_unit: QuantityUnit
    commodity_price: float
    price_type: PriceType
