"""
Global taste repository interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from .entities import GlobalTasteScore


class IGlobalTasteRepository(ABC):
    """
    Read/write contract for the user_global_taste PostgreSQL table.
    Stores long-term cross-platform commodity (and future location/quantity) taste.
    """

    @abstractmethod
    def get_weights(
        self,
        profile_id: int,
        dimension_type: str,
    ) -> dict[str, float]:
        """
        Return decay-adjusted net weights for all keys of one dimension.
        Used at feed time when the global session has no commodity data.
        """

    @abstractmethod
    def get_score(
        self,
        profile_id: int,
        dimension_type: str,
        dimension_key: str,
    ) -> GlobalTasteScore | None:
        """Return the full score record for one key, or None if absent."""

    @abstractmethod
    def apply_promotion_delta(
        self,
        profile_id: int,
        dimension_type: str,
        dimension_key: str,
        pos_delta: float,
    ) -> None:
        """
        Atomically add pos_delta to the existing positive_score.
        Creates the row if absent. Called by the nightly promotion job.
        """

    @abstractmethod
    def bulk_apply_promotion(
        self,
        deltas: list[tuple[int, str, str, float]],
    ) -> None:
        """
        Bulk upsert: list of (profile_id, dimension_type, dimension_key, pos_delta).
        More efficient for the nightly job that processes many users.
        """
