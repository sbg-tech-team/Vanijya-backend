"""KYC / KYB status use case."""
from __future__ import annotations

from app.modules.verification.application.schemas import (
    VerificationDocStatus,
    VerificationStatusResponse,
)
from app.modules.verification.domain.entities import DocRecord
from app.modules.verification.domain.interfaces.repository import IVerificationRepository


def _to_status(record: DocRecord | None) -> VerificationDocStatus:
    if record is None:
        return VerificationDocStatus(status="not_submitted")
    return VerificationDocStatus(
        status=record.status,
        document_type=record.document_type,
        verified_at=record.verified_at,
    )


def get_verification_status(
    repo: IVerificationRepository, profile_id: int
) -> VerificationStatusResponse:
    records = repo.list_records(profile_id)
    kyc = next((r for r in records if r.verification_category == "kyc"), None)
    kyb = next((r for r in records if r.verification_category == "kyb"), None)
    return VerificationStatusResponse(kyc=_to_status(kyc), kyb=_to_status(kyb))
