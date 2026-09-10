"""SQLAlchemy implementation of ISafetyRepository.

This is the only file in the safety module that touches the database.
Queries are ported verbatim from app_old/modules/safety/service.py so the
returned data — including the Profile outerjoin — is unchanged.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.profile.data.models import Profile
from app.modules.safety.data.models import UserBlock, UserReport
from app.modules.safety.domain.entities import BlockedUser, Report
from app.modules.safety.domain.interfaces.repository import ISafetyRepository


def _to_report(r: UserReport) -> Report:
    return Report(
        id=r.id,
        target_type=r.target_type,
        target_id=r.target_id,
        reason=r.reason,
        status=r.status,
        created_at=r.created_at,
    )


class SafetyRepository(ISafetyRepository):

    def __init__(self, db: Session):
        self.db = db

    # -- blocks ---------------------------------------------------------------

    def block_exists(self, blocker_id: UUID, blocked_id: UUID) -> bool:
        return self.db.query(UserBlock).filter(
            UserBlock.blocker_id == blocker_id,
            UserBlock.blocked_id == blocked_id,
        ).first() is not None

    def add_block(self, blocker_id: UUID, blocked_id: UUID) -> None:
        self.db.add(UserBlock(blocker_id=blocker_id, blocked_id=blocked_id))
        self.db.commit()

    def remove_block(self, blocker_id: UUID, blocked_id: UUID) -> bool:
        row = self.db.query(UserBlock).filter(
            UserBlock.blocker_id == blocker_id,
            UserBlock.blocked_id == blocked_id,
        ).first()
        if not row:
            return False
        self.db.delete(row)
        self.db.commit()
        return True

    def list_blocked(
        self, blocker_id: UUID, page: int, limit: int
    ) -> tuple[list[BlockedUser], int]:
        base = self.db.query(UserBlock).filter(UserBlock.blocker_id == blocker_id)
        total = base.count()
        rows = (
            base.outerjoin(Profile, Profile.users_id == UserBlock.blocked_id)
            .with_entities(
                UserBlock.blocked_id,
                UserBlock.blocked_at,
                Profile.name,
                Profile.avatar_url,
            )
            .order_by(UserBlock.blocked_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        return [
            BlockedUser(
                blocked_id=r.blocked_id,
                blocked_at=r.blocked_at,
                name=r.name,
                avatar_url=r.avatar_url,
            )
            for r in rows
        ], total

    def either_blocked(self, user_a: UUID, user_b: UUID) -> bool:
        return self.db.query(UserBlock).filter(
            (
                (UserBlock.blocker_id == user_a) & (UserBlock.blocked_id == user_b)
            ) | (
                (UserBlock.blocker_id == user_b) & (UserBlock.blocked_id == user_a)
            )
        ).first() is not None

    # -- reports --------------------------------------------------------------

    def report_exists(self, reporter_id: UUID, target_type: str, target_id: UUID) -> bool:
        return self.db.query(UserReport).filter(
            UserReport.reporter_id == reporter_id,
            UserReport.target_type == target_type,
            UserReport.target_id == target_id,
        ).first() is not None

    def add_report(
        self,
        reporter_id: UUID,
        target_type: str,
        target_id: UUID,
        reason: str,
        description: str | None,
    ) -> Report:
        report = UserReport(
            reporter_id=reporter_id,
            target_type=target_type,
            target_id=target_id,
            reason=reason,
            description=description,
        )
        self.db.add(report)
        self.db.commit()
        self.db.refresh(report)
        return _to_report(report)

    def list_reports(
        self, reporter_id: UUID, page: int, limit: int
    ) -> tuple[list[Report], int]:
        base = self.db.query(UserReport).filter(UserReport.reporter_id == reporter_id)
        total = base.count()
        rows = (
            base.order_by(UserReport.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        return [_to_report(r) for r in rows], total
