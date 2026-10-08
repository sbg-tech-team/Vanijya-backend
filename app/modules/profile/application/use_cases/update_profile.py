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
from app.modules.translation.domain.names import clean_owner_names, merge_owner_names

_BUSINESS_FIELDS = {"business_name", "city", "state", "latitude", "longitude"}
_EMBEDDING_FIELDS = {"commodities", "latitude", "longitude", "quantity_min", "quantity_max"}


# Disconnected (2026-10-06): accepted payload.interests (if an old client
# still sends it) and diffed/wrote it. Kept, not deleted.
# def update_profile(repo: IProfileRepository, user_id: UUID, payload: ProfileUpdate) -> ProfileResponse:
#     profile = repo.get_profile_for_user(user_id)
#     if not profile:
#         raise ProfileNotFoundError("Profile not found")
#
#     data = payload.model_dump(exclude_unset=True)
#
#     qmin = data.get("quantity_min", float(profile.quantity_min))
#     qmax = data.get("quantity_max", float(profile.quantity_max))
#     if qmin and qmax and qmin > qmax:
#         raise ProfileValidationError("quantity_min cannot exceed quantity_max")
#
#     scalar_fields = {
#         k: v for k, v in data.items()
#         if k not in _BUSINESS_FIELDS and k not in ("commodities", "interests")
#     }
#     business_fields = {k: v for k, v in data.items() if k in _BUSINESS_FIELDS}
#
#     commodity_to_add: set[int] = set()
#     commodity_to_remove: set[int] = set()
#     if "commodities" in data:
#         current = {pc.commodity_id for pc in profile.commodities}
#         requested = set(data["commodities"])
#         commodity_to_remove = current - requested
#         commodity_to_add = requested - current
#
#     interest_to_add: set[int] = set()
#     interest_to_remove: set[int] = set()
#     if "interests" in data:
#         current = {pi.interest_id for pi in profile.interests}
#         requested = set(data["interests"])
#         interest_to_remove = current - requested
#         interest_to_add = requested - current
#
#     repo.update_profile(
#         user_id=user_id,
#         scalar_fields=scalar_fields,
#         business_fields=business_fields,
#         commodity_to_add=commodity_to_add,
#         commodity_to_remove=commodity_to_remove,
#         interest_to_add=interest_to_add,
#         interest_to_remove=interest_to_remove,
#     )
#
#     if _EMBEDDING_FIELDS & set(data.keys()):
#         _upsert_user_embedding(repo, user_id)
#
#     profile = repo.get_profile_for_user(user_id)
#     if not profile:
#         raise ProfileNotFoundError("Profile not found after update")
#     posts_count = repo.count_posts_for_profile(profile.id)
#     return _to_response(profile, posts_count=posts_count)


def update_profile(repo: IProfileRepository, user_id: UUID, payload: ProfileUpdate) -> ProfileResponse:
    profile = repo.get_profile_for_user(user_id)
    if not profile:
        raise ProfileNotFoundError("Profile not found")

    data = payload.model_dump(exclude_unset=True)

    qmin = data.get("quantity_min", float(profile.quantity_min))
    qmax = data.get("quantity_max", float(profile.quantity_max))
    if qmin and qmax and qmin > qmax:
        raise ProfileValidationError("quantity_min cannot exceed quantity_max")

    # "interests" is accepted (if an old client still sends it) and ignored.
    scalar_fields = {
        k: v for k, v in data.items()
        if k not in _BUSINESS_FIELDS and k not in ("commodities", "interests", "name_i18n")
    }

    # The name per language. Changing the name drops every generated
    # spelling (it was made from the old name); spellings the person sends
    # are stored as theirs.
    if "name" in data or "name_i18n" in data:
        new_name = (data.get("name") or profile.name).strip()
        try:
            owner_names = clean_owner_names(data.get("name_i18n"))
        except ValueError as e:
            raise ProfileValidationError(str(e))
        if "name" in data:
            scalar_fields["name"] = new_name
        scalar_fields["name_i18n"] = merge_owner_names(
            new_name, owner_names,
            existing=getattr(profile, "name_i18n", None),
            name_changed=new_name != profile.name,
        )
    business_fields = {k: v for k, v in data.items() if k in _BUSINESS_FIELDS}

    commodity_to_add: set[int] = set()
    commodity_to_remove: set[int] = set()
    if "commodities" in data:
        current = {pc.commodity_id for pc in profile.commodities}
        requested = set(data["commodities"])
        commodity_to_remove = current - requested
        commodity_to_add = requested - current

    repo.update_profile(
        user_id=user_id,
        scalar_fields=scalar_fields,
        business_fields=business_fields,
        commodity_to_add=commodity_to_add,
        commodity_to_remove=commodity_to_remove,
    )

    if _EMBEDDING_FIELDS & set(data.keys()):
        _upsert_user_embedding(repo, user_id)

    profile = repo.get_profile_for_user(user_id)
    if not profile:
        raise ProfileNotFoundError("Profile not found after update")
    posts_count = repo.count_posts_for_profile(profile.id)
    return _to_response(profile, posts_count=posts_count)
