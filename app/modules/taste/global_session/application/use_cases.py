"""
Global session use cases — application layer.

Imports from domain/ interfaces only. Never imports from data/.
"""
from __future__ import annotations

from app.modules.taste.global_session.domain.interfaces import IGlobalSessionRepository


class WriteGlobalDelta:
    """Push a commodity delta from one module into global session."""

    def __init__(self, repo: IGlobalSessionRepository) -> None:
        self._repo = repo

    def execute(self, profile_id: int, delta: dict[str, float]) -> None:
        self._repo.write_commodity_delta(profile_id, delta)


class ReadGlobalWeights:
    """Return decay-adjusted commodity weights from global session."""

    def __init__(self, repo: IGlobalSessionRepository) -> None:
        self._repo = repo

    def execute(self, profile_id: int) -> dict[str, float]:
        if not self._repo.session_exists(profile_id):
            return {}
        return self._repo.read_commodity_weights(profile_id)


class ReadAllCommodityData:
    """
    Return raw commodity data for the nightly promotion job.
    No decay — the promotion job needs raw pos/neg/conf/cnt.
    """

    def __init__(self, repo: IGlobalSessionRepository) -> None:
        self._repo = repo

    def execute(self, profile_id: int) -> dict[str, dict[str, float]]:
        return self._repo.read_all_commodity_data(profile_id)


class ClearGlobalSession:
    """Delete the global session hash after successful nightly promotion."""

    def __init__(self, repo: IGlobalSessionRepository) -> None:
        self._repo = repo

    def execute(self, profile_id: int) -> None:
        self._repo.clear(profile_id)
