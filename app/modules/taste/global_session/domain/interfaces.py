"""
Global session repository interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from .entities import GlobalDimScore


class IGlobalSessionRepository(ABC):
    """
    Read/write contract for the cross-module Redis global session hash.
    Active dimension: commodity.  Placeholders: location, quantity.
    """

    @abstractmethod
    def write_commodity_delta(
        self,
        profile_id: int,
        delta: dict[str, float],
    ) -> None:
        """Atomically add commodity pos deltas from one module sync."""

    @abstractmethod
    def read_commodity_weights(self, profile_id: int) -> dict[str, float]:
        """Return decay-adjusted net scores for all commodity keys."""

    @abstractmethod
    def read_commodity_score(
        self,
        profile_id: int,
        commodity_key: str,
    ) -> GlobalDimScore:
        """Return the full score record for one commodity key."""

    @abstractmethod
    def read_all_commodity_data(
        self,
        profile_id: int,
    ) -> dict[str, dict[str, float]]:
        """
        Return raw {commodity_key: {pos, neg, conf, cnt}} for the nightly
        promotion job. No decay applied — job needs raw values.
        """

    @abstractmethod
    def clear(self, profile_id: int) -> None:
        """Delete the global session after successful nightly promotion."""

    @abstractmethod
    def session_exists(self, profile_id: int) -> bool:
        """Return True if a live global session hash exists."""
