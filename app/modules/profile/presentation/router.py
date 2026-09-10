from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from uuid import UUID

from app.dependencies import get_current_user, get_onboarding_user_id, get_onboarding_claims, CurrentUser
from app.core.security.jwt_handler import OnboardingClaims
from app.core.config import settings
from app.modules.onboarding.application.use_cases.service import create_session
from app.modules.onboarding.domain.interfaces.repository import IOnboardingRepository
from app.modules.onboarding.presentation.dependencies import get_onboarding_repo
from app.modules.profile.domain.interfaces.repository import IProfileRepository
from app.modules.profile.presentation.dependencies import get_profile_repo as _get_repo
from app.modules.profile.presentation.schemas import (
    ProfileCreate,
    ProfileUpdate,
    UserCreate,
    FcmTokenUpdate,
)
from app.modules.profile.application.use_cases.service import (
    create_user,
    create_profile,
    get_my_profile,
    get_profile_by_id,
    get_profile_by_user_id,
    delete_profile,
    delete_user,
    update_profile,
    get_avatar_upload_url,
    save_avatar_url,
    update_fcm_token,
    ProfileConflictError,
    ProfileNotFoundError,
    ProfileStorageUnavailableError,
    ProfileValidationError,
    UserConflictError,
)
from app.shared.utils.response import ok

router = APIRouter(prefix="/profile", tags=["Profile"])


# ---------------------------------------------------------------------------
# Onboarding Step 1 — create user row
# Requires onboarding_token (carries phone + country code from Firebase).
# ---------------------------------------------------------------------------

@router.post("/user", status_code=201)
def create_user_api(
    claims: OnboardingClaims = Depends(get_onboarding_claims),
    repo: IProfileRepository = Depends(_get_repo),
):
    payload = UserCreate(phone_number=claims.phone_number, country_code=claims.country_code)
    try:
        result = create_user(repo, claims.user_id, payload)
        return ok(result, "User created successfully")
    except UserConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))


# ---------------------------------------------------------------------------
# Onboarding Step 2 — create profile → issues first access + refresh token
# Requires onboarding_token.
# ---------------------------------------------------------------------------

@router.post("/", status_code=201)
def create_profile_api(
    payload: ProfileCreate,
    request: Request,
    current_user_id: UUID = Depends(get_onboarding_user_id),
    repo: IProfileRepository = Depends(_get_repo),
    onboarding_repo: IOnboardingRepository = Depends(get_onboarding_repo),
):
    try:
        result = create_profile(repo, current_user_id, payload)
    except ProfileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ProfileConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ProfileValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    ip = request.client.host if request.client else None
    # create_session belongs to the onboarding module and takes its repository.
    access_token, refresh_token = create_session(
        onboarding_repo, current_user_id, result.id, ip_address=ip
    )

    return ok(
        {
            "profile": result,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        },
        "Profile created successfully.",
    )


# ---------------------------------------------------------------------------
# My profile — JWT protected
# ---------------------------------------------------------------------------

@router.get("/me")
def get_my_profile_api(
    cu: CurrentUser = Depends(get_current_user),
    repo: IProfileRepository = Depends(_get_repo),
):
    try:
        result = get_my_profile(repo, cu.user_id)
        return ok(result, "Profile fetched successfully")
    except ProfileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------------------------------------------------------------------
# Update profile — JWT protected
# ---------------------------------------------------------------------------

@router.patch("/")
def update_profile_api(
    payload: ProfileUpdate,
    cu: CurrentUser = Depends(get_current_user),
    repo: IProfileRepository = Depends(_get_repo),
):
    try:
        result = update_profile(repo, cu.user_id, payload)
        return ok(result, "Profile updated successfully")
    except ProfileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ProfileValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# FCM token — JWT protected
# ---------------------------------------------------------------------------

@router.patch("/user/fcm-token")
def update_fcm_token_api(
    payload: FcmTokenUpdate,
    cu: CurrentUser = Depends(get_current_user),
    repo: IProfileRepository = Depends(_get_repo),
):
    try:
        update_fcm_token(repo, cu.user_id, payload.fcm_token)
        return ok(message="FCM token updated")
    except ProfileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------------------------------------------------------------------
# Avatar upload — JWT protected
# profile_id comes from the token (cu.profile_id) — client sends nothing extra
# ---------------------------------------------------------------------------

@router.get("/avatar-upload-url")
async def get_avatar_upload_url_api(
    content_type: str = Query(..., description="image/jpeg | image/png | image/webp"),
    cu: CurrentUser = Depends(get_current_user),
    repo: IProfileRepository = Depends(_get_repo),
):
    """
    Step 1 of avatar upload:
      GET this endpoint → receive a signed upload URL.
      PUT image bytes to that URL (Content-Type header must match).
      PATCH /profile/avatar with { avatar_url } to persist to DB.
    """
    try:
        result = await get_avatar_upload_url(repo, cu.profile_id, content_type)
        return ok(result, "Upload URL generated")
    except ProfileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ProfileValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/avatar")
async def save_avatar_url_api(
    avatar_url: str = Body(..., embed=True, description="Public URL returned after Supabase upload"),
    cu: CurrentUser = Depends(get_current_user),
    repo: IProfileRepository = Depends(_get_repo),
):
    try:
        result = await save_avatar_url(repo, cu.profile_id, avatar_url)
        return ok(result, "Avatar updated successfully")
    except ProfileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ProfileValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ProfileStorageUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))


# ---------------------------------------------------------------------------
# Delete — JWT protected
# ---------------------------------------------------------------------------

@router.delete("/")
def delete_profile_api(
    cu: CurrentUser = Depends(get_current_user),
    repo: IProfileRepository = Depends(_get_repo),
):
    try:
        delete_profile(repo, cu.user_id)
        return ok(message="Profile deleted successfully")
    except ProfileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/user")
def delete_user_api(
    cu: CurrentUser = Depends(get_current_user),
    repo: IProfileRepository = Depends(_get_repo),
):
    try:
        delete_user(repo, cu.user_id)
        return ok(message="User and all associated data deleted successfully")
    except ProfileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------------------------------------------------------------------
# Public profile view — JWT protected, profile_id in path
# Self-view redirects to /profile/me
# ---------------------------------------------------------------------------

@router.get("/{profile_id}")
def get_profile_api(
    profile_id: int,
    posts_cursor: int | None = None,
    cu: CurrentUser = Depends(get_current_user),
    repo: IProfileRepository = Depends(_get_repo),
):
    if cu.profile_id == profile_id:
        return RedirectResponse(url="/profile/me", status_code=307)
    try:
        result = get_profile_by_id(
            repo, profile_id,
            viewer_user_id=cu.user_id,
            viewer_profile_id=cu.profile_id,
            posts_cursor=posts_cursor,
        )
        return ok(result, "Profile fetched successfully")
    except ProfileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------------------------------------------------------------------
# Public profile view by user UUID — JWT protected
# Self-view redirects to /profile/me
# ---------------------------------------------------------------------------

@router.get("/by-user/{user_id}")
def get_profile_by_user_api(
    user_id: UUID,
    posts_cursor: int | None = None,
    cu: CurrentUser = Depends(get_current_user),
    repo: IProfileRepository = Depends(_get_repo),
):
    if cu.user_id == user_id:
        return RedirectResponse(url="/profile/me", status_code=307)
    try:
        result = get_profile_by_user_id(
            repo, user_id,
            viewer_user_id=cu.user_id,
            viewer_profile_id=cu.profile_id,
            posts_cursor=posts_cursor,
        )
        return ok(result, "Profile fetched successfully")
    except ProfileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
