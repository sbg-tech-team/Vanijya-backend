from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import CurrentUser, get_current_user
from app.modules.verification.application.use_cases.service import (
    get_verification_status,
    verify_document,
)
from app.modules.verification.domain.entities import ProfileRef
from app.modules.verification.domain.exceptions import ProfileNotFoundError, VerificationError
from app.modules.verification.domain.interfaces.repository import IVerificationRepository
from app.modules.verification.domain.interfaces.verifier import IDocumentVerifier
from app.modules.verification.presentation.dependencies import (
    get_document_verifier,
    get_verification_repo,
)
from app.modules.verification.presentation.schemas import (
    AadhaarVerifyRequest,
    GstVerifyRequest,
    IecVerifyRequest,
    PanVerifyRequest,
    VerificationStatusResponse,
)
from app.shared.utils.response import ok

router = APIRouter(prefix="/verification", tags=["Verification"])


def _get_profile(repo: IVerificationRepository, user_id) -> ProfileRef:
    profile = repo.get_profile_by_user(user_id)
    if not profile:
        raise ProfileNotFoundError("Profile not found. Complete onboarding first.")
    return profile


def _run(repo, verifier, user_id, document_type, document_number, **kwargs):
    """Shared flow: resolve profile -> verify -> map domain errors to HTTP."""
    try:
        profile = _get_profile(repo, user_id)
    except ProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    try:
        return verify_document(
            repo, verifier, profile, document_type, document_number, **kwargs
        )
    except VerificationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# KYC
# ---------------------------------------------------------------------------

@router.post("/kyc/pan", status_code=200)
def verify_pan(
    payload: PanVerifyRequest,
    cu: CurrentUser = Depends(get_current_user),
    repo: IVerificationRepository = Depends(get_verification_repo),
    verifier: IDocumentVerifier = Depends(get_document_verifier),
):
    """Verify PAN card for KYC. Updates profile.is_user_verified on success."""
    record = _run(
        repo, verifier, cu.user_id, "pan", payload.id_number,
        name=payload.name, dob=payload.dob,
    )
    return ok(
        {"document_type": record.document_type, "status": record.status, "verified_at": record.verified_at},
        "PAN verification complete.",
    )


@router.post("/kyc/aadhaar", status_code=501)
def verify_aadhaar(
    payload: AadhaarVerifyRequest,
    cu: CurrentUser = Depends(get_current_user),
    repo: IVerificationRepository = Depends(get_verification_repo),
):
    """Aadhaar verification — API provider not yet decided."""
    raise HTTPException(
        status_code=501,
        detail="Aadhaar verification is not yet available. API provider TBD.",
    )


# ---------------------------------------------------------------------------
# KYB
# ---------------------------------------------------------------------------

@router.post("/kyb/gst", status_code=200)
def verify_gst(
    payload: GstVerifyRequest,
    cu: CurrentUser = Depends(get_current_user),
    repo: IVerificationRepository = Depends(get_verification_repo),
    verifier: IDocumentVerifier = Depends(get_document_verifier),
):
    """Verify GST number for KYB. For Traders and Brokers. Updates profile.is_business_verified on success."""
    record = _run(repo, verifier, cu.user_id, "gst", payload.gstin)
    return ok(
        {"document_type": record.document_type, "status": record.status, "verified_at": record.verified_at},
        "GST verification complete.",
    )


@router.post("/kyb/iec", status_code=200)
def verify_iec(
    payload: IecVerifyRequest,
    cu: CurrentUser = Depends(get_current_user),
    repo: IVerificationRepository = Depends(get_verification_repo),
    verifier: IDocumentVerifier = Depends(get_document_verifier),
):
    """Verify IEC for KYB. For Exporters only. Updates profile.is_business_verified on success."""
    record = _run(repo, verifier, cu.user_id, "iec", payload.iec_number)
    return ok(
        {"document_type": record.document_type, "status": record.status, "verified_at": record.verified_at},
        "IEC verification complete.",
    )


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@router.get("/status", response_model=VerificationStatusResponse, status_code=200)
def verification_status(
    cu: CurrentUser = Depends(get_current_user),
    repo: IVerificationRepository = Depends(get_verification_repo),
):
    """Get the current KYC and KYB verification status for the logged-in user."""
    try:
        profile = _get_profile(repo, cu.user_id)
    except ProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return get_verification_status(repo, profile.profile_id)
