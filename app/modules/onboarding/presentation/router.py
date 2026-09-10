import os
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer

from app.core.config import settings
from app.core.security.jwt_handler import (
    create_access_token,
    create_onboarding_token,
    decode_access_token,
)
from app.modules.onboarding.application.use_cases.service import (
    create_session,
    issue_onboarding_token,
    refresh_session,
    revoke_session_by_jti,
    verify_firebase_token,
)
from app.modules.onboarding.domain.exceptions import OnboardingDomainError
from app.modules.onboarding.domain.interfaces.firebase import IFirebaseVerifier
from app.modules.onboarding.domain.interfaces.repository import IOnboardingRepository
from app.modules.onboarding.presentation.dependencies import (
    get_firebase_verifier,
    get_onboarding_repo,
)
from app.modules.onboarding.presentation.schemas import (
    FirebaseVerifyRequest,
    LogoutRequest,
    RefreshTokenRequest,
    TokenPairResponse,
    VerifyOTPResponse,
)
from app.shared.utils.response import ok

router = APIRouter(prefix="/auth", tags=["Auth"])
_bearer = OAuth2PasswordBearer(tokenUrl="/auth/token")


# ---------------------------------------------------------------------------
# GET /auth/dev-token  — local testing only, blocked in production
# ---------------------------------------------------------------------------

@router.get("/dev-token")
def dev_token(
    name: str,
    repo: IOnboardingRepository = Depends(get_onboarding_repo),
):
    """
    Returns a valid access token for any profile whose name matches `name`.
    Only works when DEBUG=true is set in the environment.
    Usage: GET /auth/dev-token?name=test1
    """
    if os.getenv("DEBUG", "").lower() != "true":
        raise HTTPException(status_code=404, detail="Not found")

    profile = repo.find_profile_by_name(name)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"No profile found with name '{name}'")

    token = create_access_token(
        user_id=profile.user_id,
        session_id=uuid4(),
        profile_id=profile.profile_id,
    )
    return {
        "access_token": token,
        "user_id": str(profile.user_id),
        "profile_id": profile.profile_id,
        "name": profile.name,
    }


# ---------------------------------------------------------------------------
# POST /auth/firebase-verify
# ---------------------------------------------------------------------------

@router.post("/firebase-verify", status_code=200)
def firebase_verify(
    payload: FirebaseVerifyRequest,
    request: Request,
    repo: IOnboardingRepository = Depends(get_onboarding_repo),
    verifier: IFirebaseVerifier = Depends(get_firebase_verifier),
):
    """
    Exchange a Firebase ID token for either:
    - onboarding_token  → new / incomplete user, proceed to profile creation
    - access_token + refresh_token  → returning user, ready to use the app
    """
    ip = request.client.host if request.client else None

    try:
        phone_number, country_code = verify_firebase_token(verifier, payload.firebase_id_token)
    except (ValueError, OnboardingDomainError) as e:
        raise HTTPException(status_code=401, detail=str(e))

    existing_user = repo.find_user_by_phone(country_code, phone_number)

    # Brand-new user — no DB row yet
    if existing_user is None:
        onboarding_token = issue_onboarding_token(phone_number, country_code)
        return ok(
            VerifyOTPResponse(is_new_user=True, onboarding_token=onboarding_token),
            "OTP verified. Use the onboarding token to complete registration.",
        )

    # User exists but never finished onboarding (no profile)
    if existing_user.profile_id is None:
        onboarding_token = create_onboarding_token(
            existing_user.user_id, phone_number, country_code
        )
        return ok(
            VerifyOTPResponse(is_new_user=True, onboarding_token=onboarding_token),
            "OTP verified. Use the onboarding token to complete registration.",
        )

    # Returning user — create a fresh session and issue token pair
    access_token, refresh_token = create_session(
        repo,
        existing_user.user_id,
        existing_user.profile_id,
        device_info=payload.device_info,
        ip_address=ip,
    )
    return ok(
        VerifyOTPResponse(
            is_new_user=False,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user_id=str(existing_user.user_id),
            profile_id=existing_user.profile_id,
        ),
        "Welcome back.",
    )


# ---------------------------------------------------------------------------
# POST /auth/refresh
# ---------------------------------------------------------------------------

@router.post("/refresh", response_model=TokenPairResponse, status_code=200)
def refresh_tokens(
    payload: RefreshTokenRequest,
    repo: IOnboardingRepository = Depends(get_onboarding_repo),
):
    """Exchange a valid refresh token for a new access + refresh token pair."""
    try:
        new_access, new_refresh = refresh_session(repo, payload.refresh_token)
    except (ValueError, OnboardingDomainError) as e:
        raise HTTPException(status_code=401, detail=str(e))

    return TokenPairResponse(access_token=new_access, refresh_token=new_refresh)


# ---------------------------------------------------------------------------
# POST /auth/logout
# ---------------------------------------------------------------------------

@router.post("/logout", status_code=200)
def logout(
    payload: LogoutRequest,
    repo: IOnboardingRepository = Depends(get_onboarding_repo),
    token: str = Depends(_bearer),
):
    """
    Revoke the current session.
    The client must send its access token in the Authorization header.
    """
    try:
        claims = decode_access_token(token)
        session_id = claims.session_id
    except HTTPException:
        # Token already expired/invalid — treat as already logged out
        return ok(None, "Logged out.")

    revoke_session_by_jti(repo, session_id)
    return ok(None, "Logged out successfully.")
