"""Report use cases.

Takes primitives, not the Pydantic request model — the application layer must
not import from presentation/. Return shapes match app_old exactly.
"""
from __future__ import annotations

from uuid import UUID

from app.modules.safety.domain.entities import Report
from app.modules.safety.domain.exceptions import DuplicateReportError, SelfReportError
from app.modules.safety.domain.interfaces.repository import ISafetyRepository


def _to_dict(r: Report) -> dict:
    return {
        "id": r.id,
        "target_type": r.target_type,
        "target_id": str(r.target_id),
        "reason": r.reason,
        "status": r.status,
        "created_at": r.created_at,
    }


def submit_report(
    repo: ISafetyRepository,
    reporter_id: UUID,
    target_type: str,
    target_id: UUID,
    reason: str,
    description: str | None = None,
) -> dict:
    if target_type == "user" and reporter_id == target_id:
        raise SelfReportError("Cannot report yourself.")
    if repo.report_exists(reporter_id, target_type, target_id):
        raise DuplicateReportError("You have already reported this.")
    return _to_dict(repo.add_report(reporter_id, target_type, target_id, reason, description))


def list_my_reports(
    repo: ISafetyRepository, reporter_id: UUID, page: int = 1, limit: int = 20
) -> dict:
    rows, total = repo.list_reports(reporter_id, page=page, limit=limit)
    return {
        "reports": [_to_dict(r) for r in rows],
        "total": total,
        "page": page,
        "limit": limit,
    }
