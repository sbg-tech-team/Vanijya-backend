"""
Pydantic schemas for the Connections module.

Legacy UserCreate / UserUpdate (old "Users" table) have been removed.
The acting user is now always identified via JWT (get_current_user_id dependency).
"""
from __future__ import annotations
from uuid import UUID
from pydantic import BaseModel, field_validator


class SearchPayload(BaseModel):
    """Custom vector search without a registered user_id (e.g. during signup preview)."""
    commodity:     list[str]   # e.g. ["rice", "cotton"]
    role:          str         # "trader" | "broker" | "exporter"
    latitude_raw:  float
    longitude_raw: float
    qty_min_mt:    int
    qty_max_mt:    int


class SeenPayload(BaseModel):
    """User IDs of recommendation cards the client has shown to the user."""
    user_ids: list[UUID]

    @field_validator("user_ids")
    @classmethod
    def max_fifty(cls, v: list[UUID]) -> list[UUID]:
        if len(v) > 50:
            raise ValueError("Maximum 50 user IDs per call")
        return v
