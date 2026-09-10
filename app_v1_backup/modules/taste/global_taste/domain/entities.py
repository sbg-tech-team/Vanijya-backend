"""
Global taste domain entities — pure Python, no external dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GlobalTasteScore:
    """
    One row of user_global_taste, decoded into a domain entity.
    Represents the current persistent cross-platform taste for one dimension key.
    """
    profile_id: int
    dimension_type: str    # "commodity" | "location" | "quantity"
    dimension_key: str     # e.g. "42" (commodity_id)
    positive_score: float = 0.0
    negative_score: float = 0.0
    event_count: int = 0
    last_event_at_unix: int = 0


@dataclass(frozen=True)
class PromotionCandidate:
    """
    One dimension key that passed all three promotion gates and is ready
    to be written into persistent global taste.
    """
    profile_id: int
    dimension_type: str
    dimension_key: str
    delta: float           # 0.15 × global_delta — the amount to add to persistent
