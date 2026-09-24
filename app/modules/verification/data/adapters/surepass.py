"""Surepass KYC/KYB adapter.

The endpoint paths and validity checks are ported from
app_old/modules/verification/service.py.

The one thing this must get right is WHICH kind of failure happened. Surepass
answers `success: false` both when the document is genuinely bad and when it
cannot look at the document at all — expired token, exhausted quota, its own
outage. The original code called all of that DocumentRejectedError, so for
three months every user was told their PAN had failed while the real cause was
an expired trial token. So: transport and account problems raise
ProviderUnavailableError, and only a verdict about the document itself raises
DocumentRejectedError.
"""
from __future__ import annotations

import logging
import os

import requests

from app.modules.verification.domain.exceptions import (
    DocumentRejectedError,
    ProviderUnavailableError,
)
from app.modules.verification.domain.interfaces.verifier import IDocumentVerifier

log = logging.getLogger(__name__)

# sandbox    -> https://sandbox.surepass.io/api/v1
# production -> https://kyc-api.surepass.io/api/v1
_SUREPASS_BASE_URL = os.getenv("SUREPASS_BASE_URL", "https://sandbox.surepass.io/api/v1")

# Without this a hung provider hangs the request thread indefinitely; there was
# no timeout at all before.
_TIMEOUT_S = 20

# Substrings that mean "our account, not their document". Surepass returns
# these with HTTP 200 and success:false, identically shaped to a real
# rejection, so the message is the only thing left to go on. Matched
# case-insensitively, and deliberately about billing/credentials only.
_ACCOUNT_PROBLEM_MARKERS = (
    "token is expired",
    "token has expired",
    "invalid token",
    "unauthorized",
    "unauthenticated",
    "subscription",
    "credits",
    "quota",
    "rate limit",
)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.getenv('SUREPASS_TOKEN')}",
        "Content-Type": "application/json",
    }


def _post(path: str, payload: dict, label: str) -> dict:
    """One request, with every not-about-the-document failure separated out.

    Returns the `data` object on success. Raises ProviderUnavailableError when
    we could not get a verdict, DocumentRejectedError when we got one and it
    was negative.
    """
    if not os.getenv("SUREPASS_TOKEN"):
        raise ProviderUnavailableError(
            "Document verification is not configured."
        )

    try:
        response = requests.post(
            f"{_SUREPASS_BASE_URL}{path}",
            headers=_headers(),
            json=payload,
            timeout=_TIMEOUT_S,
        )
    except requests.RequestException as exc:
        raise ProviderUnavailableError(
            f"Could not reach the verification provider: {exc}"
        ) from exc

    # 401/403 credentials, 429 quota, 5xx their problem — none is a verdict.
    if response.status_code in (401, 403, 429) or response.status_code >= 500:
        log.error("surepass %s: HTTP %s — %s", label, response.status_code,
                  response.text[:200])
        raise ProviderUnavailableError(
            f"The verification provider returned {response.status_code}."
        )

    try:
        body = response.json()
    except ValueError as exc:
        # An HTML error page would previously blow up on .json() and surface
        # as a 500.
        raise ProviderUnavailableError(
            "The verification provider returned an unreadable response."
        ) from exc

    if not body.get("success"):
        message = str(body.get("message") or response.text)
        if any(m in message.lower() for m in _ACCOUNT_PROBLEM_MARKERS):
            log.error("surepass %s: account problem — %s", label, message[:200])
            raise ProviderUnavailableError(
                f"The verification provider could not process the request: {message}"
            )
        raise DocumentRejectedError(f"{label} verification failed: {message}")

    return body.get("data", {})


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
        data = _post("/pan/pan-adv-v3",
                     {"id_number": id_number, "name": name, "dob": dob}, "PAN")
        if "EXISTING AND VALID" not in data.get("pan_status", ""):
            raise DocumentRejectedError(f"PAN is not valid: {data.get('pan_status')}")
        return data

    def _gst(self, gstin: str) -> dict:
        data = _post("/corporate/gstin", {"id_number": gstin}, "GST")
        if data.get("gstin_status") != "Active":
            raise DocumentRejectedError(f"GST is not active: {data.get('gstin_status')}")
        return data

    def _iec(self, iec_number: str) -> dict:
        data = _post("/corporate/iec-details", {"iec_number": iec_number}, "IEC")
        status = data.get("personal_details", {}).get("iec_status")
        if status != "Valid":
            raise DocumentRejectedError(f"IEC is not valid: {status}")
        return data
