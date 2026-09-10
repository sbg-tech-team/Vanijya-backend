"""Firebase OTP verification and onboarding token issuance.

The Firebase SDK now lives in data/adapters/firebase.py behind IFirebaseVerifier;
this file keeps only the phone-splitting rule and token issuance, both ported
from app_old/modules/auth/service.py.
"""
from __future__ import annotations

import uuid

from app.core.security.jwt_handler import create_onboarding_token
from app.modules.onboarding.domain.exceptions import MissingPhoneNumberError
from app.modules.onboarding.domain.interfaces.firebase import IFirebaseVerifier


def split_phone(phone: str) -> tuple[str, str]:
    """(phone_number, country_code) — app_old's exact rule."""
    if phone.startswith("+91"):
        return phone[3:], "+91"
    country_code = phone[:3] if len(phone) > 3 and phone[3:4].isdigit() else phone[:3]
    return phone[len(country_code):], country_code


def verify_firebase_token(
    verifier: IFirebaseVerifier, firebase_id_token: str
) -> tuple[str, str]:
    """
    Verify a Firebase ID token issued after phone OTP.
    Returns (phone_number, country_code).
    Raises InvalidFirebaseTokenError on invalid / expired tokens.
    Raises MissingPhoneNumberError when the token carries no phone claim.
    """
    decoded = verifier.verify_id_token(firebase_id_token)

    phone = decoded.get("phone_number")
    if not phone:
        raise MissingPhoneNumberError(
            "Token does not contain a phone number — wrong sign-in method?"
        )
    return split_phone(phone)


def issue_onboarding_token(phone_number: str, country_code: str) -> str:
    """Short-lived onboarding token for brand-new users before profile creation."""
    return create_onboarding_token(uuid.uuid4(), phone_number, country_code)
