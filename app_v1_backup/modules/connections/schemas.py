"""
Pydantic schemas for the Connections module.

Legacy UserCreate / UserUpdate (old "Users" table) have been removed.
The acting user is now always identified via JWT (get_current_user_id dependency).
"""
from __future__ import annotations
from uuid import UUID
from pydantic import BaseModel, Field, field_validator


class MessageRequestCreate(BaseModel):
    """Optional body for sending a message request — an opening line that becomes
    the first message of the conversation once the receiver accepts.

    commodity_ids / role_id are the target profile's commodities and role, sent by
    the client so the taste layer can record the signal without an extra DB query.
    """
    first_message: str | None = Field(default=None, max_length=2000)
    commodity_ids: list[int] = Field(default_factory=list)
    role_id: int | None = None


class FollowCreate(BaseModel):
    """Optional body for a follow — the target profile's commodities and role,
    sent by the client so taste can record the signal without an extra DB query."""
    commodity_ids: list[int] = Field(default_factory=list)
    role_id: int | None = None


class ProfileViewSignal(BaseModel):
    """Fired when the user opens a profile card. Redis-only taste signal — no DB
    write. commodity_ids / role_id belong to the viewed profile."""
    target_id: UUID
    commodity_ids: list[int] = Field(default_factory=list)
    role_id: int | None = None


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
