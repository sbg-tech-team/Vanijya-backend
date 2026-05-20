from typing import Optional
from datetime import datetime

from pydantic import BaseModel


class PanVerifyRequest(BaseModel):
    id_number: str   # PAN e.g. "ABCDE1234F"
    name: str        # name as per PAN
    dob: str         # "YYYY-MM-DD"


class AadhaarVerifyRequest(BaseModel):
    aadhaar_number: str


class GstVerifyRequest(BaseModel):
    gstin: str


class IecVerifyRequest(BaseModel):
    iec_number: str


class VerificationDocStatus(BaseModel):
    status: str                          # "verified" | "error" | "not_submitted"
    document_type: Optional[str] = None  # "pan" | "aadhaar" | "gst" | "iec"
    verified_at: Optional[datetime] = None


class VerificationStatusResponse(BaseModel):
    kyc: VerificationDocStatus
    kyb: VerificationDocStatus
