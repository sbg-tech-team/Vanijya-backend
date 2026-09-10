from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user, CurrentUser
from app.modules.profile.models import Profile
from app.modules.verification.schemas import (
    AadhaarVerifyRequest,
    GstVerifyRequest,
    IecVerifyRequest,
    PanVerifyRequest,
    VerificationStatusResponse,
)
from app.modules.verification.service import (
    get_verification_status,
    verify_document,
)
from app.shared.utils.response import ok

router = APIRouter(prefix="/verification", tags=["Verification"])


def _get_profile(db: Session, user_id) -> Profile:
    profile = db.query(Profile).filter(Profile.users_id == user_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found. Complete onboarding first.")
    return profile


# ---------------------------------------------------------------------------
# KYC
# ---------------------------------------------------------------------------

@router.post("/kyc/pan", status_code=200)
def verify_pan(
    payload: PanVerifyRequest,
    db: Session = Depends(get_db),
    cu: CurrentUser = Depends(get_current_user),
):
    """Verify PAN card for KYC. Updates profile.is_user_verified on success."""
    profile = _get_profile(db, cu.user_id)
    try:
        record = verify_document(
            db,
            profile,
            "pan",
            payload.id_number,
            name=payload.name,
            dob=payload.dob,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok(
        {"document_type": record.document_type, "status": record.status, "verified_at": record.verified_at},
        "PAN verification complete.",
    )


@router.post("/kyc/aadhaar", status_code=501)
def verify_aadhaar(
    payload: AadhaarVerifyRequest,
    db: Session = Depends(get_db),
    cu: CurrentUser = Depends(get_current_user),
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
    db: Session = Depends(get_db),
    cu: CurrentUser = Depends(get_current_user),
):
    """Verify GST number for KYB. For Traders and Brokers. Updates profile.is_business_verified on success."""
    profile = _get_profile(db, cu.user_id)
    try:
        record = verify_document(db, profile, "gst", payload.gstin)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok(
        {"document_type": record.document_type, "status": record.status, "verified_at": record.verified_at},
        "GST verification complete.",
    )


@router.post("/kyb/iec", status_code=200)
def verify_iec(
    payload: IecVerifyRequest,
    db: Session = Depends(get_db),
    cu: CurrentUser = Depends(get_current_user),
):
    """Verify IEC for KYB. For Exporters only. Updates profile.is_business_verified on success."""
    profile = _get_profile(db, cu.user_id)
    try:
        record = verify_document(db, profile, "iec", payload.iec_number)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ok(
        {"document_type": record.document_type, "status": record.status, "verified_at": record.verified_at},
        "IEC verification complete.",
    )


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@router.get("/status", response_model=VerificationStatusResponse, status_code=200)
def verification_status(
    db: Session = Depends(get_db),
    cu: CurrentUser = Depends(get_current_user),
):
    """Get the current KYC and KYB verification status for the logged-in user."""
    profile = _get_profile(db, cu.user_id)
    return get_verification_status(db, profile.id)
