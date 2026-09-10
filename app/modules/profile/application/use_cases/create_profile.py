from __future__ import annotations

from typing import Iterable
from uuid import UUID

from app.modules.profile.application.schemas import (
    CommodityOut,
    InterestOut,
    ProfileCreate,
    ProfileResponse,
    UserCreate,
    UserResponse,
)
from app.modules.profile.domain.exceptions import (
    ProfileConflictError,
    ProfileNotFoundError,
    ProfileValidationError,
    UserConflictError,
)
from app.modules.profile.domain.interfaces.repository import IProfileRepository
from app.modules.profile.application.use_cases.rebuild_embedding import _upsert_user_embedding


def _uniq(ids: Iterable[int]) -> list[int]:
    return list(dict.fromkeys(ids))


def _to_response(profile, posts_count: int = 0) -> ProfileResponse:
    return ProfileResponse(
        id=profile.id,
        user_id=profile.users_id,
        name=profile.name,
        role_id=profile.role_id,
        phone_number=profile.user.phone_number,
        country_code=profile.user.country_code,
        is_user_verified=profile.is_user_verified,
        is_business_verified=profile.is_business_verified,
        followers_count=profile.followers_count,
        following_count=profile.following_count,
        posts_count=posts_count,
        commodities=[CommodityOut.model_validate(pc.commodity) for pc in profile.commodities],
        interests=[InterestOut.model_validate(pi.interest) for pi in profile.interests],
        business_name=profile.business.business_name,
        city=profile.business.city,
        state=profile.business.state,
        latitude=profile.business.latitude,
        longitude=profile.business.longitude,
        avatar_url=profile.avatar_url,
    )


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_role(repo: IProfileRepository, role_id: int) -> None:
    if not repo.role_exists(role_id):
        raise ProfileValidationError(
            f"Invalid role_id: {role_id}. Use 1=Trader, 2=Broker, 3=Exporter."
        )


def _validate_commodity_ids(repo: IProfileRepository, ids: list[int]) -> list[int]:
    ids = _uniq(ids)
    if not ids:
        return []
    missing = repo.find_missing_commodity_ids(ids)
    if missing:
        raise ProfileValidationError(f"Invalid commodity_ids: {missing}")
    return ids


def _validate_interest_ids(repo: IProfileRepository, ids: list[int]) -> list[int]:
    ids = _uniq(ids)
    if not ids:
        return []
    missing = repo.find_missing_interest_ids(ids)
    if missing:
        raise ProfileValidationError(f"Invalid interest_ids: {missing}")
    return ids


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------

def create_user(repo: IProfileRepository, user_id: UUID, payload: UserCreate) -> UserResponse:
    existing = repo.get_user(user_id)
    if existing:
        return UserResponse(
            id=existing.id,
            phone_number=existing.phone_number,
            country_code=existing.country_code,
            created_at=existing.created_at,
        )

    if repo.phone_number_exists(payload.country_code, payload.phone_number):
        raise UserConflictError("Phone number already registered")

    user = repo.create_user(user_id, payload.phone_number, payload.country_code)
    return UserResponse(
        id=user.id,
        phone_number=user.phone_number,
        country_code=user.country_code,
        created_at=user.created_at,
    )


def store_access_token(repo: IProfileRepository, user_id: UUID, token: str) -> None:
    repo.store_access_token(user_id, token)


def get_access_token(repo: IProfileRepository, user_id: UUID) -> str | None:
    return repo.get_access_token(user_id)


def update_fcm_token(repo: IProfileRepository, user_id: UUID, fcm_token: str) -> None:
    repo.update_fcm_token(user_id, fcm_token)


def get_profile_id_for_user(repo: IProfileRepository, user_id: UUID) -> int:
    profile_id = repo.get_profile_id_for_user(user_id)
    if profile_id is None:
        raise ProfileNotFoundError("Profile not found for this user")
    return profile_id


def delete_user(repo: IProfileRepository, user_id: UUID) -> None:
    repo.delete_user(user_id)


# ---------------------------------------------------------------------------
# Profile creation
# ---------------------------------------------------------------------------

def create_profile(repo: IProfileRepository, user_id: UUID, payload: ProfileCreate) -> ProfileResponse:
    if not repo.get_user(user_id):
        raise ProfileNotFoundError("User not found — create user first via POST /profile/user")

    if repo.user_has_profile(user_id):
        raise ProfileConflictError("Profile already exists for this user")

    if payload.quantity_min > payload.quantity_max:
        raise ProfileValidationError("quantity_min cannot be greater than quantity_max")

    _validate_role(repo, payload.role_id)
    commodity_ids = _validate_commodity_ids(repo, payload.commodities)
    interest_ids = _validate_interest_ids(repo, payload.interests)

    repo.create_profile(
        user_id=user_id,
        role_id=payload.role_id,
        name=payload.name.strip(),
        qty_min=payload.quantity_min,
        qty_max=payload.quantity_max,
        business_name=payload.business_name.strip() if payload.business_name else None,
        city=payload.city.strip() if payload.city else None,
        state=payload.state.strip() if payload.state else None,
        latitude=payload.latitude,
        longitude=payload.longitude,
        commodity_ids=commodity_ids,
        interest_ids=interest_ids,
    )

    _upsert_user_embedding(repo, user_id)

    profile = repo.get_profile_for_user(user_id)
    if not profile:
        raise ProfileNotFoundError("Profile not found after creation")
    return _to_response(profile, posts_count=0)
