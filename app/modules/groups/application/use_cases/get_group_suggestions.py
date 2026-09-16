"""
Group recommendation engine — two-stage pgvector ANN + activity reranking.

All functions are pure business logic; no FastAPI imports.
Domain exceptions from app.modules.groups.domain.exceptions are raised on error.
"""
from __future__ import annotations

from uuid import UUID


from app.modules.groups.data.models import (
    Group,
    GroupActivityCache,
    GroupMember,
)
from app.modules.groups.application.schemas import GroupSuggestionOut
from app.modules.groups.domain.interfaces.repository import IGroupsRepository
from app.modules.groups.domain.exceptions import (
    GroupBusinessProfileMissingError,
    GroupProfileNotFoundError,
)
from app.modules.groups.recommendation.vectors import (
    build_group_vector,  # noqa: F401 — re-exported for callers that import from here
    build_match_reasons,
    compute_activity_score,
    compute_final_score,
)
from app.modules.connections.recommendation.vectors import build_query_vector
from app.recommendation.amplify import commodity_boost, commodity_ids_for, get_amplify_weights

# Re-import shared helpers from create_group to avoid duplication
from app.modules.groups.application.use_cases.record_view import MODULE as _MODULE
from app.modules.groups.application.use_cases.create_group import (
    _build_group_out,
    _get_profile_or_raise,
)

# role_id -> string name used in vector encoding
ROLE_ID_TO_NAME = {1: "trader", 2: "broker", 3: "exporter"}
TOP_K = 20


def get_group_suggestions(
    repo: IGroupsRepository,
    user_id: UUID,
    top_k: int = TOP_K,
    page: int = 1,
    limit: int = 20,
    rc=None,
) -> dict:
    """
    Two-stage group recommendation:
      Stage 1 — pgvector HNSW cosine ANN (<=> operator) pre-filters candidates.
      Stage 2 — activity reranking via group_activity_cache.
      Final    — weighted blend (75 % semantic + 25 % activity).
    """
    # 1. Load user profile
    profile = _get_profile_or_raise(repo, user_id)

    user_commodities = [pc.commodity.name.lower() for pc in profile.commodities]
    user_role = ROLE_ID_TO_NAME.get(profile.role_id, "trader")

    if not profile.business:
        raise GroupBusinessProfileMissingError(
            "Business profile not set up — complete onboarding to get group suggestions."
        )

    want_vec = build_query_vector(
        commodity_list=user_commodities,
        role=user_role,
        lat=float(profile.business.latitude),
        lon=float(profile.business.longitude),
        qty_min=int(profile.quantity_min),
        qty_max=int(profile.quantity_max),
    )

    vec_str = "[" + ",".join(str(v) for v in want_vec) + "]"

    # 2. Get user's current group memberships
    member_set = {
        row[0]
        for row in [(g,) for g in repo.member_group_ids(user_id)]
    }

    # 3. HNSW ANN: fetch top candidates, excluding private groups.
    #    Overfetch (top_k * 4) to allow Python-side member filtering.
    candidate_rows = repo.ann_group_candidates(vec_str, limit=top_k * 4)

    # Filter out groups the user already belongs to
    candidates = [
        (r["group_id"], float(r["similarity"]))
        for r in candidate_rows
        if r["group_id"] not in member_set
    ][:top_k * 2]  # keep a buffer for activity reranking

    if not candidates:
        return {"total": 0, "page": page, "limit": limit, "results": []}

    # 4. Load groups + activity caches in bulk
    group_ids = [gid for gid, _ in candidates]

    groups = {
        g.id: g
        for g in repo.get_groups_by_ids(group_ids).values()
    }
    activities = repo.get_activity_cache(group_ids)

    # 5. Activity reranking — weighted blend
    scored: list[tuple[float, Group, float, float]] = []
    # Amplify (Mechanism 1): blended taste (persistent + module + global session)
    # boosts semantic similarity BEFORE the activity blend:
    #     final = 0.75 x (semantic x commodity_boost) + 0.25 x activity
    # app_old did this; app_new had dropped it, so suggestions were unpersonalised.
    try:
        weights = get_amplify_weights(repo.session, rc, profile.id, _MODULE) if rc is not None else {}
    except Exception:
        weights = {}

    for gid, sim in candidates:
        group = groups.get(gid)
        if group is None:
            continue

        cache = activities.get(gid)
        act = compute_activity_score(
            messages_24h=cache.messages_24h if cache else 0,
            active_members_7d=cache.active_members_7d if cache else 0,
            member_growth_7d=cache.member_growth_7d if cache else 0,
        )
        boost = (
            commodity_boost(weights, commodity_ids_for(repo.session, group.commodity or []))
            if weights else 1.0
        )
        final = compute_final_score(sim * boost, act)
        scored.append((final, group, sim, act))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_k]

    # 6. Build response
    all_results: list[GroupSuggestionOut] = []
    for final_score, group, sim, act in top:
        reasons = build_match_reasons(
            user_commodities=user_commodities,
            user_role=user_role,
            group_commodities=group.commodity or [],
            group_target_roles=group.target_roles or [],
            cosine_sim=sim,
            act_score=act,
        )
        all_results.append(
            GroupSuggestionOut(
                group=_build_group_out(group, None),
                match_score=final_score,
                match_reasons=reasons,
            )
        )

    start = (page - 1) * limit
    return {
        "total": len(all_results),
        "page": page,
        "limit": limit,
        "results": all_results[start: start + limit],
    }
