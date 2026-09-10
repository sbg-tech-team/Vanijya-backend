"""Document verification use case.

Behaviour is ported from app_old/modules/verification/service.py:

* pre-check failures (KYB before KYC, wrong doc for role) raise -> router 400
* a provider *rejection* is NOT an HTTP error: it is stored as a
  `status="error"` row and the endpoint still returns 200
* NotImplementedError propagates unchanged
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.modules.verification.domain.entities import ProfileRef, VerificationOutcome
from app.modules.verification.domain.exceptions import (
    DocumentRejectedError,
    InvalidKybDocumentError,
    KycRequiredError,
)
from app.modules.verification.domain.interfaces.repository import IVerificationRepository
from app.modules.verification.domain.interfaces.verifier import IDocumentVerifier

CATEGORY_MAP = {
    "pan": "kyc",
    "aadhaar": "kyc",
    "gst": "kyb",
    "iec": "kyb",
}

# KYB document expected per role: 1=Trader, 2=Broker, 3=Exporter
ROLE_KYB_DOC = {1: "gst", 2: "gst", 3: "iec"}
_ROLE_NAMES = {1: "Trader", 2: "Broker", 3: "Exporter"}


def verify_document(
    repo: IVerificationRepository,
    verifier: IDocumentVerifier,
    profile: ProfileRef,
    document_type: str,
    document_number: str,
    **api_kwargs,
) -> VerificationOutcome:
    category = CATEGORY_MAP[document_type]
    now = datetime.now(timezone.utc)

    # KYB requires KYC to be completed first
    if category == "kyb" and not profile.is_user_verified:
        raise KycRequiredError(
            "Complete identity verification (KYC) before verifying your business."
        )

    # Enforce role-based KYB document rule
    if category == "kyb":
        expected = ROLE_KYB_DOC.get(profile.role_id)
        if expected and document_type != expected:
            raise InvalidKybDocumentError(
                f"{_ROLE_NAMES.get(profile.role_id, 'Your role')} must use '{expected}' "
                f"for business verification, not '{document_type}'."
            )

    api_response = None
    status = "error"
    error_message = None
    verified_at = None
    api_provider = "sandbox"

    try:
        api_provider, api_response = verifier.verify(
            document_type, document_number, **api_kwargs
        )
        status = "verified"
        verified_at = now
    except NotImplementedError:
        raise
    except DocumentRejectedError as exc:
        status = "error"
        error_message = str(exc)

    return repo.save_verification(
        profile_id=profile.profile_id,
        document_type=document_type,
        category=category,
        document_number=document_number,
        status=status,
        api_provider=api_provider,
        api_response=api_response,
        error_message=error_message,
        verified_at=verified_at,
        now=now,
        mark_profile_verified=(status == "verified"),
    )
