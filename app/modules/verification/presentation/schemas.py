from pydantic import BaseModel

from app.modules.verification.application.schemas import (  # noqa: F401
    VerificationDocStatus,
    VerificationStatusResponse,
)


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
