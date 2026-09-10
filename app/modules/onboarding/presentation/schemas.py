from typing import Optional

from pydantic import BaseModel

from app.core.config import settings


class FirebaseVerifyRequest(BaseModel):
    firebase_id_token: str
    device_info: Optional[str] = None  # e.g. "iPhone 15 / iOS 17"


class VerifyOTPResponse(BaseModel):
    is_new_user: bool
    token_type: str = "bearer"

    # New user — no DB session yet; use these two tokens to complete onboarding
    onboarding_token: Optional[str] = None

    # Returning user — fully registered, ready to use the app
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_in: Optional[int] = None   # seconds until access token expires
    user_id: Optional[str] = None
    profile_id: Optional[int] = None


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60


class LogoutRequest(BaseModel):
    # Client can optionally pass the refresh token to explicitly revoke this session.
    # If omitted the server will revoke the session identified by the access token's jti.
    refresh_token: Optional[str] = None
