import logging
import os
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer

from app.core.config import settings
from app.core.rate_limiter import RateLimiter
from app.core.redis_client import get_redis

log = logging.getLogger(__name__)
from app.core.security.jwt_handler import (
    create_access_token,
    create_onboarding_token,
    decode_access_token,
)
from app.modules.calling.application.use_cases import service as calling_service
from app.modules.calling.domain.interfaces.repository import ICallingRepository
from app.modules.calling.presentation.dependencies import get_calling_repo
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

# Auth endpoints are the ones worth brute-forcing, and they were the only
# unthrottled writes left. Per-IP sliding window; a Redis outage must not lock
# people out of signing in, so a limiter failure is logged, not raised.
_limiter = RateLimiter()
_VERIFY_LIMIT, _VERIFY_WINDOW = 10, 60      # 10 sign-in attempts per minute per IP
_REFRESH_LIMIT, _REFRESH_WINDOW = 30, 60    # refresh is legitimate but not hot


def _throttle(key: str, limit: int, window: int) -> None:
    try:
        _limiter.check(get_redis(), key, limit=limit, window=window)
    except HTTPException:
        raise                      # 429 — the limiter did its job
    except Exception as exc:
        # Redis down must never lock people out of signing in.
        log.warning("rate limiting unavailable for %s: %s", key, exc)


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
    _throttle(f"auth:verify:{ip or 'unknown'}", _VERIFY_LIMIT, _VERIFY_WINDOW)

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
    request: Request,
    repo: IOnboardingRepository = Depends(get_onboarding_repo),
):
    """Exchange a valid refresh token for a new access + refresh token pair."""
    ip = request.client.host if request.client else "unknown"
    _throttle(f"auth:refresh:{ip}", _REFRESH_LIMIT, _REFRESH_WINDOW)
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
    calling_repo: ICallingRepository = Depends(get_calling_repo),
    token: str = Depends(_bearer),
):
    """
    Revoke the current session, and unregister this device from push if the
    client sent its `fcm_token`.

    Both here rather than in a separate endpoint: logout is one thing a client
    already does, and a second call it could forget or fail to make is how a
    signed-out phone keeps ringing for the previous account.
    """
    try:
        claims = decode_access_token(token)
        session_id = claims.session_id
    except HTTPException:
        # Token already expired/invalid — treat as already logged out
        return ok(None, "Logged out.")

    revoke_session_by_jti(repo, session_id)

    if payload.fcm_token:
        # Best-effort: a push row that outlives the session is a privacy
        # problem, but failing to remove it must not fail the logout itself —
        # the client has already been told the session is gone.
        try:
            calling_service.unregister_device(
                calling_repo, user_id=claims.user_id, fcm_token=payload.fcm_token,
            )
        except Exception:
            log.warning("logout: could not unregister device for %s", claims.user_id)

    return ok(None, "Logged out successfully.")
