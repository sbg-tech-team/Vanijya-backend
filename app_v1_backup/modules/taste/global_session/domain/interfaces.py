"""
Global session repository interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from .entities import GlobalDimScore


class IGlobalSessionRepository(ABC):
    """
    Read/write contract for the cross-module Redis global session hash.
    Dimension-type-generic — active: commodity, city, state.
    Scaffolded, no writer yet: trade_intent. Placeholder: quantity.
    """

    @abstractmethod
    def write_dimension_delta(
        self,
        profile_id: int,
        dimension_type: str,
        delta: dict[str, dict[str, float]],
    ) -> None:
        """Atomically add pos/neg/conf deltas for one dimension from one module sync."""

    @abstractmethod
    def read_dimension_weights(self, profile_id: int, dimension_type: str) -> dict[str, float]:
        """Return decay-adjusted net scores for all keys in one dimension."""

    @abstractmethod
    def read_dimension_score(
        self,
        profile_id: int,
        dimension_type: str,
        key: str,
    ) -> GlobalDimScore:
        """Return the full score record for one dimension key."""

    @abstractmethod
    def read_all_dimension_data(
        self,
        profile_id: int,
    ) -> dict[str, dict[str, dict[str, float]]]:
        """
        Return raw {dimension_type: {key: {pos, neg, conf, cnt}}} for every
        dimension type present, for the nightly promotion job. One HGETALL,
        no decay applied — job needs raw values.
        """

    @abstractmethod
    def clear(self, profile_id: int) -> None:
        """Delete the global session after successful nightly promotion."""

    @abstractmethod
    def session_exists(self, profile_id: int) -> bool:
        """Return True if a live global session hash exists."""

    @abstractmethod
    def scan_active_profile_ids(self) -> list[int]:
        """Return every profile_id with a live session:global:* key (nightly job)."""
