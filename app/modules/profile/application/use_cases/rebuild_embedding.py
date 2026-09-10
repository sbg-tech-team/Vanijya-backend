from __future__ import annotations

from uuid import UUID

from app.modules.connections.recommendation.vectors import build_candidate_vector
from app.modules.profile.domain.interfaces.repository import IProfileRepository
from app.modules.profile.domain.value_objects import RoleEnum


def _upsert_user_embedding(repo: IProfileRepository, user_id: UUID) -> None:
    """
    Rebuild the IS vector and post-feed vector for a user profile and upsert
    into user_embeddings.
    Called after profile create and after updates that touch embedding-relevant fields.
    """
    profile = repo.get_profile_for_user(user_id)
    if not profile:
        return

    commodity_names = [pc.commodity.name.lower() for pc in profile.commodities if pc.commodity]
    role_str = RoleEnum.name_for(profile.role_id)

    vec = build_candidate_vector(
        commodity_list=commodity_names,
        role=role_str,
        lat=float(profile.business.latitude),
        lon=float(profile.business.longitude),
        qty_min=int(profile.quantity_min),
        qty_max=int(profile.quantity_max),
    )

    from app.modules.post.recommendation.vectors import build_user_feed_vector
    commodity_ids = [pc.commodity_id for pc in profile.commodities]
    post_vec = build_user_feed_vector(
        commodity_ids=commodity_ids,
        role_id=profile.role_id,
        lat=float(profile.business.latitude),
        lon=float(profile.business.longitude),
        commodity_quantity=(float(profile.quantity_min) + float(profile.quantity_max)) / 2,
    )

    repo.upsert_embedding(user_id, vec, post_vec)
