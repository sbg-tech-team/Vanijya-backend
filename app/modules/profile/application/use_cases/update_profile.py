from __future__ import annotations

from uuid import UUID

from app.modules.profile.application.schemas import (
    ProfileResponse,
    ProfileUpdate,
)
from app.modules.profile.domain.exceptions import (
    ProfileNotFoundError,
    ProfileValidationError,
)
from app.modules.profile.domain.interfaces.repository import IProfileRepository
from app.modules.profile.application.use_cases.rebuild_embedding import _upsert_user_embedding
from app.modules.profile.application.use_cases.create_profile import _to_response

_BUSINESS_FIELDS = {"business_name", "city", "state", "latitude", "longitude"}
_EMBEDDING_FIELDS = {"commodities", "latitude", "longitude", "quantity_min", "quantity_max"}


def update_profile(repo: IProfileRepository, user_id: UUID, payload: ProfileUpdate) -> ProfileResponse:
    profile = repo.get_profile_for_user(user_id)
    if not profile:
        raise ProfileNotFoundError("Profile not found")

    data = payload.model_dump(exclude_unset=True)

    qmin = data.get("quantity_min", float(profile.quantity_min))
    qmax = data.get("quantity_max", float(profile.quantity_max))
    if qmin and qmax and qmin > qmax:
        raise ProfileValidationError("quantity_min cannot exceed quantity_max")

    scalar_fields = {
        k: v for k, v in data.items()
        if k not in _BUSINESS_FIELDS and k not in ("commodities", "interests")
    }
    business_fields = {k: v for k, v in data.items() if k in _BUSINESS_FIELDS}

    commodity_to_add: set[int] = set()
    commodity_to_remove: set[int] = set()
    if "commodities" in data:
        current = {pc.commodity_id for pc in profile.commodities}
        requested = set(data["commodities"])
        commodity_to_remove = current - requested
        commodity_to_add = requested - current

    interest_to_add: set[int] = set()
    interest_to_remove: set[int] = set()
    if "interests" in data:
        current = {pi.interest_id for pi in profile.interests}
        requested = set(data["interests"])
        interest_to_remove = current - requested
        interest_to_add = requested - current

    repo.update_profile(
        user_id=user_id,
        scalar_fields=scalar_fields,
        business_fields=business_fields,
        commodity_to_add=commodity_to_add,
        commodity_to_remove=commodity_to_remove,
        interest_to_add=interest_to_add,
        interest_to_remove=interest_to_remove,
    )

    if _EMBEDDING_FIELDS & set(data.keys()):
        _upsert_user_embedding(repo, user_id)

    profile = repo.get_profile_for_user(user_id)
    if not profile:
        raise ProfileNotFoundError("Profile not found after update")
    posts_count = repo.count_posts_for_profile(profile.id)
    return _to_response(profile, posts_count=posts_count)
