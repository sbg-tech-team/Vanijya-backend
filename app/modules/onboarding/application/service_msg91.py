import random
import string
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx

from app.core.config import settings
from app.core.security.jwt_handler import create_onboarding_token

MSG91_BASE = "https://control.msg91.com/api/v5/otp"

# Dev-mode in-memory store: "country_code:phone" -> (otp, expires_at)
_dev_otp_store: dict[str, tuple[str, datetime]] = {}
_DEV_OTP_EXPIRE_MINUTES = 10


def _mobile(country_code: str, phone_number: str) -> str:
    return f"{country_code.lstrip('+')}{phone_number}"


def _phone_key(country_code: str, phone_number: str) -> str:
    return f"{country_code}:{phone_number}"


def send_otp(phone_number: str, country_code: str) -> None:
    if settings.DEV_MODE:
        otp = "".join(random.choices(string.digits, k=6))
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=_DEV_OTP_EXPIRE_MINUTES)
        _dev_otp_store[_phone_key(country_code, phone_number)] = (otp, expires_at)
        print(f"\n[DEV] OTP for {country_code} {phone_number}: {otp}\n")
        return

    params: dict = {
        "authkey": settings.MSG91_AUTH_KEY,
        "mobile": _mobile(country_code, phone_number),
    }
    if settings.MSG91_TEMPLATE_ID:
        params["template_id"] = settings.MSG91_TEMPLATE_ID

    resp = httpx.post(
        MSG91_BASE,
        params=params,
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("type") != "success":
        raise RuntimeError(f"MSG91 error: {data.get('message', 'unknown error')}")


def verify_otp(phone_number: str, country_code: str, otp_code: str) -> None:
    """Validate OTP. Raises ValueError on failure. Does NOT issue any token."""
    if settings.DEV_MODE:
        key = _phone_key(country_code, phone_number)
        entry = _dev_otp_store.get(key)
        if not entry:
            raise ValueError("No OTP found for this number — request a new one.")
        stored_otp, expires_at = entry
        if datetime.now(timezone.utc) > expires_at:
            del _dev_otp_store[key]
            raise ValueError("OTP has expired — request a new one.")
        if otp_code != stored_otp:
            raise ValueError("Invalid OTP.")
        del _dev_otp_store[key]
    else:
        resp = httpx.get(
            f"{MSG91_BASE}/verify",
            params={
                "authkey": settings.MSG91_AUTH_KEY,
                "mobile": _mobile(country_code, phone_number),
                "otp": otp_code,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("type") != "success":
            raise ValueError(data.get("message", "OTP verification failed"))


def issue_onboarding_token(phone_number: str, country_code: str) -> str:
    """Create a short-lived onboarding token for new user registration."""
    return create_onboarding_token(uuid4(), phone_number, country_code)
