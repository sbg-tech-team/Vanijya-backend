"""Surepass KYC/KYB adapter.

The `requests` calls, endpoint paths and validity checks are ported verbatim
from app_old/modules/verification/service.py. Rejections raise
DocumentRejectedError, which the use case records as a `status="error"` row —
app_old used a bare ValueError for the same purpose.
"""
from __future__ import annotations

import os

import requests

from app.modules.verification.domain.exceptions import DocumentRejectedError
from app.modules.verification.domain.interfaces.verifier import IDocumentVerifier

# sandbox    -> https://sandbox.surepass.io/api/v1
# production -> https://kyc-api.surepass.io/api/v1
_SUREPASS_BASE_URL = os.getenv("SUREPASS_BASE_URL", "https://sandbox.surepass.io/api/v1")


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.getenv('SUREPASS_TOKEN')}",
        "Content-Type": "application/json",
    }


class SurepassVerifier(IDocumentVerifier):

    def verify(self, document_type: str, document_number: str, **kwargs) -> tuple[str, dict]:
        if document_type == "pan":
            return "surepass", self._pan(document_number, kwargs["name"], kwargs["dob"])
        if document_type == "gst":
            return "surepass", self._gst(document_number)
        if document_type == "iec":
            return "surepass", self._iec(document_number)
        if document_type == "aadhaar":
            raise NotImplementedError("Aadhaar verification API provider not yet decided.")
        raise NotImplementedError(f"Unsupported document type: {document_type}")

    # -- providers ------------------------------------------------------------

    def _pan(self, id_number: str, name: str, dob: str) -> dict:
        response = requests.post(
            f"{_SUREPASS_BASE_URL}/pan/pan-adv-v3",
            headers=_headers(),
            json={"id_number": id_number, "name": name, "dob": dob},
        )
        body = response.json()
        if not body.get("success"):
            raise DocumentRejectedError(
                f"PAN verification failed: {body.get('message', response.text)}"
            )
        data = body.get("data", {})
        if "EXISTING AND VALID" not in data.get("pan_status", ""):
            raise DocumentRejectedError(f"PAN is not valid: {data.get('pan_status')}")
        return data

    def _gst(self, gstin: str) -> dict:
        response = requests.post(
            f"{_SUREPASS_BASE_URL}/corporate/gstin",
            headers=_headers(),
            json={"id_number": gstin},
        )
        body = response.json()
        if not body.get("success"):
            raise DocumentRejectedError(
                f"GST verification failed: {body.get('message', response.text)}"
            )
        data = body.get("data", {})
        if data.get("gstin_status") != "Active":
            raise DocumentRejectedError(f"GST is not active: {data.get('gstin_status')}")
        return data

    def _iec(self, iec_number: str) -> dict:
        response = requests.post(
            f"{_SUREPASS_BASE_URL}/corporate/iec-details",
            headers=_headers(),
            json={"iec_number": iec_number},
        )
        body = response.json()
        if not body.get("success"):
            raise DocumentRejectedError(
                f"IEC verification failed: {body.get('message', response.text)}"
            )
        data = body.get("data", {})
        if data.get("personal_details", {}).get("iec_status") != "Valid":
            raise DocumentRejectedError(
                f"IEC is not valid: {data.get('personal_details', {}).get('iec_status')}"
            )
        return data
