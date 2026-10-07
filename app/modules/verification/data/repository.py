"""SQLAlchemy implementation of IVerificationRepository.

Only file in the verification module that touches the database. The upsert and
the profile-flag update stay in the single commit app_old used.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.profile.data.models import Profile
from app.modules.verification.data.models import VerificationRecord
from app.modules.verification.domain.entities import (
    DocRecord,
    ProfileRef,
    VerificationOutcome,
)
from app.modules.verification.domain.interfaces.repository import IVerificationRepository


class VerificationRepository(IVerificationRepository):

    def __init__(self, db: Session):
        self.db = db

    def get_profile_by_user(self, user_id: UUID) -> ProfileRef | None:
        profile = self.db.query(Profile).filter(Profile.users_id == user_id).first()
        if not profile:
            return None
        return ProfileRef(
            profile_id=profile.id,
            role_id=profile.role_id,
            is_user_verified=profile.is_user_verified,
            is_business_verified=profile.is_business_verified,
        )

    def save_verification(
        self,
        profile_id: int,
        document_type: str,
        category: str,
        document_number: str,
        status: str,
        api_provider: str,
        api_response: dict | None,
        error_message: str | None,
        verified_at: datetime | None,
        now: datetime,
        mark_profile_verified: bool,
    ) -> VerificationOutcome:
        record = (
            self.db.query(VerificationRecord)
            .filter(
                VerificationRecord.profile_id == profile_id,
                VerificationRecord.document_type == document_type,
            )
            .first()
        )
        if record is None:
            record = VerificationRecord(
                profile_id=profile_id,
                document_type=document_type,
                verification_category=category,
            )
            self.db.add(record)

        record.document_number = document_number
        record.status = status
        record.api_provider = api_provider
        record.api_response = api_response
        record.error_message = error_message
        record.verified_at = verified_at
        record.updated_at = now

        if mark_profile_verified:
            # Direct UPDATE, no SELECT first — this only ever flips one
            # column, it never needs to read the row. (get_profile_by_user
            # loaded this same profile earlier in the request, but only
            # returns a ProfileRef DTO — the ORM object has no strong
            # reference left by the time this runs, so the session's
            # weak-referencing identity map has already dropped it; a
            # db.get() here would still issue its own SELECT in practice.)
            field = {"kyc": "is_user_verified", "kyb": "is_business_verified"}.get(category)
            if field:
                self.db.query(Profile).filter(Profile.id == profile_id).update({field: True})

        self.db.commit()
        # No refresh() — document_type/status/verified_at are this
        # function's own parameters, already known, not server-generated.
        # Reading them off `record` instead would re-SELECT it anyway
        # (session default expire_on_commit=True).
        return VerificationOutcome(
            document_type=document_type,
            status=status,
            verified_at=verified_at,
        )

    def list_records(self, profile_id: int) -> list[DocRecord]:
        rows = (
            self.db.query(VerificationRecord)
            .filter(VerificationRecord.profile_id == profile_id)
            .all()
        )
        return [
            DocRecord(
                verification_category=r.verification_category,
                document_type=r.document_type,
                status=r.status,
                verified_at=r.verified_at,
            )
            for r in rows
        ]
