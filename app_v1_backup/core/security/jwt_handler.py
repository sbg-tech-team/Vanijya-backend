import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from fastapi import HTTPException

from app.core.config import settings

ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
USER_ID_CLAIM = "sub"
ONBOARDING_TOKEN_TYPE = "onboarding"
ACCESS_TOKEN_TYPE = "access"
ONBOARDING_TOKEN_EXPIRE_MINUTES = 30


def _secret() -> str:
    key = os.getenv("JWT_SECRET_KEY")
    if not key:
        raise RuntimeError(
            "JWT_SECRET_KEY is not set. "
            "Add it to your .env file and make sure load_dotenv() runs before the server starts."
        )
    return key


# ---------------------------------------------------------------------------
# Access token
# Claims: sub=user_id, pid=profile_id, jti=session_id, type, exp
# ---------------------------------------------------------------------------

@dataclass
class AccessTokenClaims:
    user_id: UUID
    profile_id: int
    session_id: UUID


def create_access_token(user_id: UUID, session_id: UUID, profile_id: int) -> str:
    """
    Issues a short-lived access token.
    - `jti` binds it to a UserSession row (enables revocation).
    - `pid` carries profile_id so no DB lookup is needed per request.
    """
    payload = {
        "sub": str(user_id),
        "pid": profile_id,
        "jti": str(session_id),
        "type": ACCESS_TOKEN_TYPE,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> AccessTokenClaims:
    """Decode and validate an access token. Raises HTTPException on any failure."""
    try:
        payload = jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Access token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid access token")

    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise HTTPException(status_code=401, detail="Invalid token type")

    raw_sub = payload.get("sub")
    raw_jti = payload.get("jti")
    raw_pid = payload.get("pid")

    if not raw_sub or not raw_jti or raw_pid is None:
        raise HTTPException(status_code=401, detail="Token missing required claims")

    try:
        return AccessTokenClaims(
            user_id=UUID(str(raw_sub)),
            profile_id=int(raw_pid),
            session_id=UUID(str(raw_jti)),
        )
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Token contains malformed claims")


# ---------------------------------------------------------------------------
# Onboarding token — 15 min, pre-profile, no DB session
# ---------------------------------------------------------------------------

def create_onboarding_token(user_id: UUID, phone_number: str, country_code: str) -> str:
    payload = {
        "sub": str(user_id),
        "phone_number": phone_number,
        "country_code": country_code,
        "token_type": ONBOARDING_TOKEN_TYPE,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ONBOARDING_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


@dataclass
class OnboardingClaims:
    user_id: UUID
    phone_number: str
    country_code: str


def decode_onboarding_token(token: str) -> UUID:
    """Validate onboarding token and return just the user_id."""
    try:
        payload = jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Onboarding token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid onboarding token")

    if payload.get("token_type") != ONBOARDING_TOKEN_TYPE:
        raise HTTPException(status_code=401, detail="Invalid token type — onboarding token required")

    raw_id = payload.get("sub")
    if raw_id is None:
        raise HTTPException(status_code=401, detail="Token missing 'sub' claim")

    try:
        return UUID(str(raw_id))
    except ValueError:
        raise HTTPException(status_code=401, detail="Token contains invalid user ID")


def decode_onboarding_claims(token: str) -> OnboardingClaims:
    """Validate onboarding token and return full claims (user_id + phone + country)."""
    try:
        payload = jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Onboarding token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid onboarding token")

    if payload.get("token_type") != ONBOARDING_TOKEN_TYPE:
        raise HTTPException(status_code=401, detail="Invalid token type — onboarding token required")

    raw_id = payload.get("sub")
    if raw_id is None:
        raise HTTPException(status_code=401, detail="Token missing 'sub' claim")

    try:
        user_id = UUID(str(raw_id))
    except ValueError:
        raise HTTPException(status_code=401, detail="Token contains invalid user ID")

    return OnboardingClaims(
        user_id=user_id,
        phone_number=payload.get("phone_number", ""),
        country_code=payload.get("country_code", ""),
    )
