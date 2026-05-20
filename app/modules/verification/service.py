import os
from datetime import datetime, timezone
from uuid import UUID

import requests
from sqlalchemy.orm import Session

from app.modules.profile.models import Profile
from app.modules.verification.models import VerificationRecord
from app.modules.verification.schemas import VerificationDocStatus, VerificationStatusResponse

# sandbox → https://sandbox.surepass.io/api/v1
# production → https://kyc-api.surepass.io/api/v1
_SUREPASS_BASE_URL = os.getenv("SUREPASS_BASE_URL", "https://sandbox.surepass.io/api/v1")


def _surepass_headers() -> dict:
    return {
        "Authorization": f"Bearer {os.getenv('SUREPASS_TOKEN')}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Individual document verification calls
# ---------------------------------------------------------------------------

def _verify_pan_surepass(id_number: str, name: str, dob: str) -> dict:
    response = requests.post(
        f"{_SUREPASS_BASE_URL}/pan/pan-adv-v3",
        headers=_surepass_headers(),
        json={"id_number": id_number, "name": name, "dob": dob},
    )
    body = response.json()
    if not body.get("success"):
        raise ValueError(f"PAN verification failed: {body.get('message', response.text)}")
    data = body.get("data", {})
    if "EXISTING AND VALID" not in data.get("pan_status", ""):
        raise ValueError(f"PAN is not valid: {data.get('pan_status')}")
    return data


def _verify_gst_surepass(gstin: str) -> dict:
    response = requests.post(
        f"{_SUREPASS_BASE_URL}/corporate/gstin",
        headers=_surepass_headers(),
        json={"id_number": gstin},
    )
    body = response.json()
    if not body.get("success"):
        raise ValueError(f"GST verification failed: {body.get('message', response.text)}")
    data = body.get("data", {})
    if data.get("gstin_status") != "Active":
        raise ValueError(f"GST is not active: {data.get('gstin_status')}")
    return data


def _verify_aadhaar(aadhaar_number: str) -> dict:
    raise NotImplementedError("Aadhaar verification API provider not yet decided.")


def _verify_iec_surepass(iec_number: str) -> dict:
    response = requests.post(
        f"{_SUREPASS_BASE_URL}/corporate/iec-details",
        headers=_surepass_headers(),
        json={"iec_number": iec_number},
    )
    body = response.json()
    if not body.get("success"):
        raise ValueError(f"IEC verification failed: {body.get('message', response.text)}")
    data = body.get("data", {})
    if data.get("personal_details", {}).get("iec_status") != "Valid":
        raise ValueError(f"IEC is not valid: {data.get('personal_details', {}).get('iec_status')}")
    return data


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

_CATEGORY_MAP = {
    "pan": "kyc",
    "aadhaar": "kyc",
    "gst": "kyb",
    "iec": "kyb",
}

# KYB document expected per role: 1=Trader, 2=Broker, 3=Exporter
_ROLE_KYB_DOC = {1: "gst", 2: "gst", 3: "iec"}


def verify_document(
    db: Session,
    profile: Profile,
    document_type: str,
    document_number: str,
    **api_kwargs,
) -> VerificationRecord:
    """
    Call the appropriate external API, persist the result in verification_records,
    and update the profile verification flags on success.
    """
    category = _CATEGORY_MAP[document_type]
    now = datetime.now(timezone.utc)

    # KYB requires KYC to be completed first
    if category == "kyb" and not profile.is_user_verified:
        raise ValueError("Complete identity verification (KYC) before verifying your business.")

    # Enforce role-based KYB document rule
    if category == "kyb":
        expected = _ROLE_KYB_DOC.get(profile.role_id)
        if expected and document_type != expected:
            role_names = {1: "Trader", 2: "Broker", 3: "Exporter"}
            raise ValueError(
                f"{role_names.get(profile.role_id, 'Your role')} must use '{expected}' for business verification, not '{document_type}'."
            )

    api_response = None
    status = "error"
    error_message = None
    verified_at = None
    api_provider = "sandbox"

    try:
        if document_type == "pan":
            api_provider = "surepass"
            api_response = _verify_pan_surepass(
                document_number,
                api_kwargs["name"],
                api_kwargs["dob"],
            )
            status = "verified"
            verified_at = now
        elif document_type == "aadhaar":
            api_provider = "placeholder"
            _verify_aadhaar(document_number)
        elif document_type == "gst":
            api_provider = "surepass"
            api_response = _verify_gst_surepass(document_number)
            status = "verified"
            verified_at = now
        elif document_type == "iec":
            api_provider = "surepass"
            api_response = _verify_iec_surepass(document_number)
            status = "verified"
            verified_at = now
    except NotImplementedError:
        raise
    except ValueError as exc:
        status = "error"
        error_message = str(exc)

    # Upsert verification record
    record = (
        db.query(VerificationRecord)
        .filter(
            VerificationRecord.profile_id == profile.id,
            VerificationRecord.document_type == document_type,
        )
        .first()
    )
    if record is None:
        record = VerificationRecord(
            profile_id=profile.id,
            document_type=document_type,
            verification_category=category,
        )
        db.add(record)

    record.document_number = document_number
    record.status = status
    record.api_provider = api_provider
    record.api_response = api_response
    record.error_message = error_message
    record.verified_at = verified_at
    record.updated_at = now

    # Update profile flags on success
    if status == "verified":
        if category == "kyc":
            profile.is_user_verified = True
        elif category == "kyb":
            profile.is_business_verified = True

    db.commit()
    db.refresh(record)
    return record


def get_verification_status(db: Session, profile_id: int) -> VerificationStatusResponse:
    records = (
        db.query(VerificationRecord)
        .filter(VerificationRecord.profile_id == profile_id)
        .all()
    )

    kyc_record = next((r for r in records if r.verification_category == "kyc"), None)
    kyb_record = next((r for r in records if r.verification_category == "kyb"), None)

    def _to_status(record: VerificationRecord | None) -> VerificationDocStatus:
        if record is None:
            return VerificationDocStatus(status="not_submitted")
        return VerificationDocStatus(
            status=record.status,
            document_type=record.document_type,
            verified_at=record.verified_at,
        )

    return VerificationStatusResponse(
        kyc=_to_status(kyc_record),
        kyb=_to_status(kyb_record),
    )
