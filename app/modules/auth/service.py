import hashlib
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID
import requests
import firebase_admin
from firebase_admin import auth as firebase_auth, credentials
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security.jwt_handler import create_access_token, create_onboarding_token
from app.modules.auth.models import UserSession

sandbox_base_url = "https://api.sandbox.co.in"




# ---------------------------------------------------------------------------
# Firebase Admin SDK initialisation
# ---------------------------------------------------------------------------

def _get_firebase_app() -> firebase_admin.App:
    try:
        return firebase_admin.get_app()
    except ValueError:
        pass

    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if sa_json:
        cred = credentials.Certificate(json.loads(sa_json))
    else:
        service_json_path = Path(__file__).resolve().parents[4] / "backend" / "service.json"
        cred = credentials.Certificate(str(service_json_path))

    return firebase_admin.initialize_app(cred)


_firebase_app = _get_firebase_app()


# ---------------------------------------------------------------------------
# Firebase token verification
# ---------------------------------------------------------------------------

def verify_firebase_token(firebase_id_token: str) -> tuple[str, str]:
    """
    Verify a Firebase ID token issued after phone OTP.
    Returns (phone_number, country_code).
    Raises ValueError on invalid / expired tokens.
    """
    try:
        decoded = firebase_auth.verify_id_token(firebase_id_token, app=_firebase_app)
    except Exception as exc:
        raise ValueError(f"Invalid Firebase token: {exc}") from exc

    phone = decoded.get("phone_number")
    if not phone:
        raise ValueError("Token does not contain a phone number — wrong sign-in method?")

    if phone.startswith("+91"):
        country_code = "+91"
        phone_number = phone[3:]
    else:
        country_code = phone[:3] if len(phone) > 3 and phone[3:4].isdigit() else phone[:3]
        phone_number = phone[len(country_code):]

    return phone_number, country_code


# ---------------------------------------------------------------------------
# Onboarding token (new / incomplete users — no DB session)
# ---------------------------------------------------------------------------

def issue_onboarding_token(phone_number: str, country_code: str) -> str:
    """Short-lived onboarding token for brand-new users before profile creation."""
    return create_onboarding_token(uuid.uuid4(), phone_number, country_code)


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

def _hash_token(raw: str) -> str:
    """SHA-256 hex digest — never store the raw refresh token."""
    return hashlib.sha256(raw.encode()).hexdigest()


def create_session(
    db: Session,
    user_id: UUID,
    profile_id: int,
    *,
    device_info: str | None = None,
    ip_address: str | None = None,
) -> tuple[str, str]:
    """
    Create a new UserSession row and issue (access_token, refresh_token).

    The refresh token is an opaque random string; only its SHA-256 hash is
    persisted.  The access token embeds session UUID as `jti` and profile_id
    as `pid` so callers never need an extra DB lookup per request.
    """
    session_id = uuid.uuid4()
    raw_refresh = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    session = UserSession(
        id=session_id,
        user_id=user_id,
        refresh_token_hash=_hash_token(raw_refresh),
        expires_at=expires_at,
        is_active=True,
        device_info=device_info,
        ip_address=ip_address,
    )
    db.add(session)
    db.commit()

    access_token = create_access_token(user_id, session_id, profile_id)
    return access_token, raw_refresh


def refresh_session(db: Session, raw_refresh_token: str) -> tuple[str, str]:
    """
    Validate a refresh token, rotate it, and return a new (access_token, refresh_token).
    Raises ValueError if the token is invalid, expired, or already revoked.
    """
    from app.modules.profile.models import Profile

    token_hash = _hash_token(raw_refresh_token)
    session = (
        db.query(UserSession)
        .filter(
            UserSession.refresh_token_hash == token_hash,
            UserSession.is_active == True,
        )
        .first()
    )

    if session is None:
        raise ValueError("Invalid or revoked refresh token.")

    if datetime.now(timezone.utc) > session.expires_at.replace(tzinfo=timezone.utc):
        session.is_active = False
        db.commit()
        raise ValueError("Refresh token has expired. Please sign in again.")

    # Fetch profile_id to keep it current in the new token
    profile_row = db.query(Profile.id).filter(Profile.users_id == session.user_id).first()
    if profile_row is None:
        raise ValueError("User profile not found.")
    profile_id: int = profile_row[0]

    # Rotate: new refresh token + new access token, same session row
    new_raw_refresh = secrets.token_urlsafe(48)
    session.refresh_token_hash = _hash_token(new_raw_refresh)
    session.last_used_at = datetime.now(timezone.utc)
    db.commit()

    new_access = create_access_token(session.user_id, session.id, profile_id)
    return new_access, new_raw_refresh


def revoke_session_by_jti(db: Session, session_id: UUID) -> None:
    """Deactivate the session identified by the JWT jti (used on logout)."""
    session = db.query(UserSession).filter(UserSession.id == session_id).first()
    if session:
        session.is_active = False
        db.commit()


def revoke_all_sessions(db: Session, user_id: UUID) -> None:
    """Force-logout: invalidate every active session for a user."""
    db.query(UserSession).filter(
        UserSession.user_id == user_id,
        UserSession.is_active == True,
    ).update({"is_active": False})
    db.commit()


# Sandbox API integrations for KYC (PAN card and GST number verification)

_sandbox_token: str | None = None
def _get_sandbox_token() -> str:
    global _sandbox_token
    if _sandbox_token:
        return _sandbox_token
    _sandbox_token = _auth_sandbox_api()
    return _sandbox_token



def _auth_sandbox_api() -> str:
    """Authenticate with sandbox apis to get a token -- fill this token directly in the headers for all the requests"""
    x_api_key = os.getenv("X-API-KEY")
    x_api_secret = os.getenv("X-API-SECRET")
    url= f"{sandbox_base_url}/authenticate"
    headers={
        "X-API-KEY": x_api_key,
        "X-API-SECRET": x_api_secret,
    }
    response = requests.post(url, headers=headers )
    
    if response.status_code == 200:
        response_json = response.json()
        token=response_json.get("access_token")
        return token
    else:
        raise ValueError(f"Authentication failed: {response.text}")

def _verify_pan_card(pan:str, user_name:str, date_of_birth:str, consent:str) -> dict:
    """We use the sandbox api to get details of the person based on the PAN card number. This is used for KYC during onboarding."""
    x_api_key = os.getenv("X-API-KEY")
    x_api_secret = os.getenv("X-API-SECRET")
    url= f"{sandbox_base_url}/kyc/pan/verify"
    headers={
        "X-API-KEY": x_api_key,
        "X-API-SECRET": x_api_secret,
        "Authorization": _get_sandbox_token()
    }
    body={
        "@entity": "in.co.sandbox.kyc.pan_verification.request",
        "pan": pan,
        "name_as_per_pan": user_name,
        "date_of_birth": date_of_birth,
        "consent": consent,
        "reason": "For onboarding customers"
        }
    response = requests.post(url, headers=headers, json=body)
    if response.status_code == 200:
        return response.json()
    elif response.status_code == 400:
        error_info = response.json()
        error_message = error_info.get("error", "Unknown error")
        raise ValueError(f"PAN verification failed: {error_message}")
    else:
        raise ValueError(f"PAN verification failed: {response.text}")


def _verify_gst_number(gstin:str) -> dict:
    """We use the sandbox api to get details of the business based on the GST number. This is used for KYC during onboarding."""
    x_api_key = os.getenv("X-API-KEY")
    x_api_secret = os.getenv("X-API-SECRET")
    url= f"{sandbox_base_url}/gst/compliance/public/gstin/verify"
    headers={
        "X-API-KEY": x_api_key,
        "X-API-SECRET": x_api_secret,
        "Authorization":_get_sandbox_token()

    }
    body={
            "gstin": gstin,
        }
    response = requests.post(url, headers=headers, json=body)
    if response.status_code == 200:
        return response.json()
    else:
        raise ValueError(f"GST verification failed: {response.text}")