from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

from app.core.database.session import SessionLocal
from app.core.security.jwt_handler import (
    OnboardingClaims,
    decode_access_token,
    decode_onboarding_claims,
    decode_onboarding_token,
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@dataclass
class CurrentUser:
    user_id: UUID
    profile_id: int


def get_current_user(token: str = Depends(oauth2_scheme)) -> CurrentUser:
    """
    Decode access token → CurrentUser(user_id, profile_id).
    Both IDs come from JWT claims — zero DB calls.
    """
    claims = decode_access_token(token)
    return CurrentUser(user_id=claims.user_id, profile_id=claims.profile_id)


def get_current_user_id(token: str = Depends(oauth2_scheme)) -> UUID:
    """Convenience dep for endpoints that only need user_id."""
    return decode_access_token(token).user_id


def get_current_profile_id(token: str = Depends(oauth2_scheme)) -> int:
    """Convenience dep for endpoints that only need profile_id."""
    return decode_access_token(token).profile_id


def get_onboarding_claims(token: str = Depends(oauth2_scheme)) -> OnboardingClaims:
    return decode_onboarding_claims(token)


def get_onboarding_user_id(token: str = Depends(oauth2_scheme)) -> UUID:
    return decode_onboarding_token(token)
