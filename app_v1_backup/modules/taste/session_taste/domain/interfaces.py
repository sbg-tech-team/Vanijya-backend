"""
Session taste repository interface — the only contract the application layer sees.
The data layer provides the concrete implementation; the domain defines the shape.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from .entities import DimScore, SessionSignal


class IModuleSessionRepository(ABC):
    """
    Read/write contract for per-module Redis session taste.

    One instance covers all dimensions for one module (identified by the
    `module` string: "post", "news", "connections", "feed", …).
    """

    @abstractmethod
    def write_signals(
        self,
        profile_id: int,
        module: str,
        signals: list[SessionSignal],
    ) -> None:
        """Atomically ingest a batch of signals. Resets the inactivity TTL."""

    @abstractmethod
    def read_dimension_scores(
        self,
        profile_id: int,
        module: str,
        dimension_type: str,
    ) -> dict[str, float]:
        """
        Return decay-adjusted net scores for every key in one dimension.
        Empty dict when session is absent or dimension has no data.
        """

    @abstractmethod
    def read_dim_score(
        self,
        profile_id: int,
        module: str,
        dimension_type: str,
        key: str,
    ) -> DimScore:
        """Return the full score record for one specific dimension key."""

    @abstractmethod
    def get_dimension_delta_and_snapshot(
        self,
        profile_id: int,
        module: str,
        dimension_type: str,
    ) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
        """
        Compute the unsynced delta (pos, neg, conf) for one cross-platform
        dimension since the last global sync.

        Returns:
            delta    — {key: {"pos", "neg", "conf"}} deltas since last sync
            snapshot — {key: {"pos", "neg", "conf"}} current raw values
                       (pass to mark_dimension_synced)
        """

    @abstractmethod
    def mark_dimension_synced(
        self,
        profile_id: int,
        module: str,
        dimension_type: str,
        snapshot: dict[str, dict[str, float]],
    ) -> None:
        """
        Record the synced pos/neg/conf snapshot so the next
        get_dimension_delta_and_snapshot call only returns the increment that
        happened after this call.
        """

    @abstractmethod
    def session_exists(self, profile_id: int, module: str) -> bool:
        """Return True if a live session hash exists in Redis."""
