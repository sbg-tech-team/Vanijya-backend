from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security.jwt_handler import create_onboarding_token, decode_access_token
from app.dependencies import get_db
from app.modules.auth.schemas import (
    FirebaseVerifyRequest,
    LogoutRequest,
    RefreshTokenRequest,
    TokenPairResponse,
    VerifyOTPResponse,
    PanVerificationRequest,
    GstVerificationRequest
)
from app.modules.auth.service import (
    create_session,
    issue_onboarding_token,
    refresh_session,
    revoke_session_by_jti,
    verify_firebase_token,
    _verify_pan_card,
    _verify_gst_number   
)
from app.modules.profile.models import User
from app.shared.utils.response import ok
from app.core.config import settings

router = APIRouter(prefix="/auth", tags=["Auth"])
_bearer = OAuth2PasswordBearer(tokenUrl="/auth/token")


# ---------------------------------------------------------------------------
# POST /auth/firebase-verify
# ---------------------------------------------------------------------------

@router.post("/firebase-verify", status_code=200)
def firebase_verify(
    payload: FirebaseVerifyRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Exchange a Firebase ID token for either:
    - onboarding_token  → new / incomplete user, proceed to profile creation
    - access_token + refresh_token  → returning user, ready to use the app
    """
    ip = request.client.host if request.client else None

    try:
        phone_number, country_code = verify_firebase_token(payload.firebase_id_token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    existing_user: User | None = db.query(User).filter(
        User.country_code == country_code,
        User.phone_number == phone_number,
    ).first()

    # Brand-new user — no DB row yet
    if existing_user is None:
        onboarding_token = issue_onboarding_token(phone_number, country_code)
        return ok(
            VerifyOTPResponse(is_new_user=True, onboarding_token=onboarding_token),
            "OTP verified. Use the onboarding token to complete registration.",
        )

    # User exists but never finished onboarding (no profile)
    if existing_user.profile is None:
        onboarding_token = create_onboarding_token(
            existing_user.id, phone_number, country_code
        )
        return ok(
            VerifyOTPResponse(is_new_user=True, onboarding_token=onboarding_token),
            "OTP verified. Use the onboarding token to complete registration.",
        )

    # Returning user — create a fresh session and issue token pair
    access_token, refresh_token = create_session(
        db,
        existing_user.id,
        existing_user.profile.id,
        device_info=payload.device_info,
        ip_address=ip,
    )
    return ok(
        VerifyOTPResponse(
            is_new_user=False,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user_id=str(existing_user.id),
            profile_id=existing_user.profile.id,
        ),
        "Welcome back.",
    )


# ---------------------------------------------------------------------------
# POST /auth/refresh
# ---------------------------------------------------------------------------

@router.post("/refresh", response_model=TokenPairResponse, status_code=200)
def refresh_tokens(
    payload: RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    """Exchange a valid refresh token for a new access + refresh token pair."""
    try:
        new_access, new_refresh = refresh_session(db, payload.refresh_token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    return TokenPairResponse(access_token=new_access, refresh_token=new_refresh)


# ---------------------------------------------------------------------------
# POST /auth/logout
# ---------------------------------------------------------------------------

@router.post("/logout", status_code=200)
def logout(
    payload: LogoutRequest,
    db: Session = Depends(get_db),
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

    revoke_session_by_jti(db, session_id)
    return ok(None, "Logged out successfully.")



# ---------------------------------------------------------------------------
# Additional endpoints for KYC (PAN and GST verification) can be added here, following a similar pattern: define a request schema, implement the logic in service.py, and create a route handler that calls the service function and returns an appropriate response.       

@router.post("/verify-pan", status_code=200)
def verify_pan_card(payload: PanVerificationRequest) -> dict:
    """Endpoint to verify PAN card details using the sandbox API."""
    try:
        pan_details = _verify_pan_card(payload.pan_number, payload.user_name, payload.date_of_birth, payload.consent)
        # print(pan_details)
        return ok(pan_details, "PAN card verified successfully.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    


@router.post("/get-gst-details",status_code=200)
def verify_gst_number(payload:GstVerificationRequest)-> dict:
    """Endpoint to verify the gst no and get details of the buissness using the sandbox API."""
    try:
        gst_details=_verify_gst_number(payload.gstin)
        # print(gst_details)
        return ok(gst_details,"GST number verified successfully.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) 
