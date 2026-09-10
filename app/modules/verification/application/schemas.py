from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class VerificationDocStatus(BaseModel):
    status: str                          # "verified" | "error" | "not_submitted"
    document_type: Optional[str] = None  # "pan" | "aadhaar" | "gst" | "iec"
    verified_at: Optional[datetime] = None


class VerificationStatusResponse(BaseModel):
    kyc: VerificationDocStatus
    kyb: VerificationDocStatus
