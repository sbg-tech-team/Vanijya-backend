"""Group view signal — Redis-only taste, no DB write.

Ported from app_old/modules/groups/service.py:872. app_new dropped this along
with the POST /api/v1/groups/view endpoint and every other amplify hook in the
groups module.
"""
from __future__ import annotations

from app.recommendation.amplify import write_commodity_signals
from app.recommendation.session_taste import ActionType

MODULE = "groups"


def record_group_view(rc, viewer_profile_id: int, commodity_ids: list[int], background_tasks=None) -> None:
    """Redis-only taste signal — the viewer opened a group / suggestion. No DB
    write. Best-effort and not something the response needs to wait on, so
    when `background_tasks` (a TaskQueue) is given, defer it instead of
    writing inline."""
    def _run() -> None:
        write_commodity_signals(
            rc, viewer_profile_id, MODULE,
            commodity_ids, ActionType.GROUP_VIEW,
        )
    if background_tasks is not None:
        background_tasks.add_task(_run)
    else:
        _run()
