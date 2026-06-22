"""
Session taste use cases — application layer.

Imports from domain/ interfaces only. Never imports from data/.
Concrete repository is injected at construction time by the composition root.
"""
from __future__ import annotations

from app.modules.taste.session_taste.domain.entities import DimScore, SessionSignal
from app.modules.taste.session_taste.domain.interfaces import IModuleSessionRepository


class WriteSignals:
    """Ingest a batch of interaction signals into the module session store."""

    def __init__(self, repo: IModuleSessionRepository) -> None:
        self._repo = repo

    def execute(
        self,
        profile_id: int,
        module: str,
        signals: list[SessionSignal],
    ) -> None:
        self._repo.write_signals(profile_id, module, signals)


class ReadDimensionWeights:
    """
    Return decay-adjusted net weights for all keys in one dimension.
    Returns empty dict when no session exists (caller should fall back to persistent).
    """

    def __init__(self, repo: IModuleSessionRepository) -> None:
        self._repo = repo

    def execute(
        self,
        profile_id: int,
        module: str,
        dimension_type: str,
    ) -> dict[str, float]:
        if not self._repo.session_exists(profile_id, module):
            return {}
        return self._repo.read_dimension_scores(profile_id, module, dimension_type)


class ReadDimScore:
    """Return the full score record (pos, neg, conf, cnt, ts) for one key."""

    def __init__(self, repo: IModuleSessionRepository) -> None:
        self._repo = repo

    def execute(
        self,
        profile_id: int,
        module: str,
        dimension_type: str,
        key: str,
    ) -> DimScore:
        return self._repo.read_dim_score(profile_id, module, dimension_type, key)


class GetCommoditySyncDelta:
    """
    Compute the unsynced commodity delta.

    Returns (delta, snapshot). Callers write delta to global session, then
    pass snapshot to MarkSynced to prevent double-counting on the next call.
    """

    def __init__(self, repo: IModuleSessionRepository) -> None:
        self._repo = repo

    def execute(
        self,
        profile_id: int,
        module: str,
    ) -> tuple[dict[str, float], dict[str, float]]:
        return self._repo.get_commodity_delta_and_snapshot(profile_id, module)


class MarkSynced:
    """Persist the commodity sync snapshot after a successful global write."""

    def __init__(self, repo: IModuleSessionRepository) -> None:
        self._repo = repo

    def execute(
        self,
        profile_id: int,
        module: str,
        snapshot: dict[str, float],
    ) -> None:
        self._repo.mark_synced(profile_id, module, snapshot)
