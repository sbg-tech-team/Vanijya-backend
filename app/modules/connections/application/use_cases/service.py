"""
Compatibility shim — re-exports everything from the individual use case modules.

All code that previously imported directly from this file continues to work
without modification. New code should import from the specific use case module.

Original sections:
  A. Follow graph       -> follow_user.py
  B. Message requests   -> send_message_request.py + respond_to_request.py
  C. User search        -> search_users.py
  D. Recommendations    -> (still inline below; unchanged)
"""
from __future__ import annotations

import logging

from typing import cast
from uuid import UUID

import redis as redis_lib

from app.modules.connections.application.formatters import fmt_profile
from app.modules.connections.domain.interfaces.repository import IConnectionsRepository
from app.modules.connections.recommendation.vectors import build_query_vector
from app.recommendation.amplify import commodity_boost, commodity_ids_for, get_amplify_weights

_MODULE = "connections"

TOP_K = 20
_SEEN_TTL = 172_800  # 48 hours

_ROLE_ID_TO_NAME = {1: "trader", 2: "broker", 3: "exporter"}

# ---------------------------------------------------------------------------
# Section A — Follow graph
# ---------------------------------------------------------------------------
from app.modules.connections.application.use_cases.follow_user import (  # noqa: F401, E402
    follow_user,
    unfollow_user,
    get_followers,
    get_following,
    is_following,
    record_profile_view,
)

# ---------------------------------------------------------------------------
# Section B — Message requests (send / withdraw / list)
# ---------------------------------------------------------------------------
from app.modules.connections.application.use_cases.send_message_request import (  # noqa: F401, E402
    send_message_request,
    withdraw_message_request,
    get_received_requests,
    get_sent_requests,
)

# ---------------------------------------------------------------------------
# Section B (continued) — Respond to request
# ---------------------------------------------------------------------------
from app.modules.connections.application.use_cases.respond_to_request import (  # noqa: F401, E402
    respond_to_request,
)

# ---------------------------------------------------------------------------
# Section C — User search
# ---------------------------------------------------------------------------
from app.modules.connections.application.use_cases.search_users import (  # noqa: F401, E402
    search_users,
    search_suggestions,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Section D — Recommendations  (pgvector HNSW cosine ANN via <=>)
# Kept here until a dedicated recommendations use case file is created.
# ---------------------------------------------------------------------------






def _to_pgvec(vec: list[float]) -> str:
    return "[" + ",".join(str(v) for v in vec) + "]"


def clear_recommendations_seen(r: redis_lib.Redis, user_id: UUID) -> None:
    """Delete the user's seen set so all recommendations resurface immediately."""
    try:
        r.delete(f"rec:seen:{user_id}")
    except Exception:
        log.warning("could not clear the seen-set for %s; recommendations may repeat", user_id)


def mark_recommendations_seen(
    r: redis_lib.Redis,
    user_id: UUID,
    seen_user_ids: list[UUID],
) -> None:
    """
    Best-effort. Stores seen recommendation user IDs in a Redis Set with a
    48-hour TTL that is set ONCE at key creation and never reset on updates.
    """
    if not seen_user_ids:
        return
    key = f"rec:seen:{user_id}"
    try:
        existed = r.exists(key)
        r.sadd(key, *[str(uid) for uid in seen_user_ids])
        if not existed:
            r.expire(key, _SEEN_TTL)
    except Exception:
        log.warning("could not record seen candidates for %s; they may be shown again", user_id)


def _get_seen_ids(r: redis_lib.Redis, user_id: UUID) -> list[str]:
    try:
        raw = cast(set, r.smembers(f"rec:seen:{user_id}"))
        return [s.decode() if isinstance(s, bytes) else s for s in raw]
    except Exception:
        return []


def get_recommendations(
    repo: IConnectionsRepository,
    r: redis_lib.Redis,
    user_id: UUID,
    page: int = 1,
    limit: int = 20,
) -> dict:
    """
    Paginated user matches for the calling user.
    1. Builds WANT vector from their profile.
    2. Runs pgvector HNSW ANN search against user_embeddings.
    3. Returns `limit` results starting at `(page-1)*limit`.
    """
    from app.modules.connections.domain.exceptions import ProfileNotFoundError

    profile = repo.load_profile(user_id)
    if not profile:
        raise ProfileNotFoundError(user_id)

    role_str = _ROLE_ID_TO_NAME.get(profile.role_id, "trader")
    commodity_names = [pc.commodity.name.lower() for pc in profile.commodities]
    want_vec = build_query_vector(
        commodity_list=commodity_names,
        role=role_str,
        lat=float(profile.business.latitude),
        lon=float(profile.business.longitude),
        qty_min=int(profile.quantity_min),
        qty_max=int(profile.quantity_max),
    )

    offset = (page - 1) * limit

    seen_ids = _get_seen_ids(r, user_id)

    total_available = repo.count_recommendable_users(user_id, seen_ids)
    rows = repo.ann_user_candidates(
        _to_pgvec(want_vec), user_id, seen_ids, limit=limit, offset=offset
    )

    top = [(round(float(row["similarity"]), 4), row["user_id"]) for row in rows]

    match_ids = [uid for _, uid in top]
    match_profiles = repo.load_profiles_bulk(match_ids)
    statuses = repo.bulk_statuses(user_id, match_ids)
    results = [
        {
            **fmt_profile(
                match_profiles[uid],
                msg_req_status=statuses.get(uid, {}).get("msg_req_status"),
                follow_status=statuses.get(uid, {}).get("follow_status", False),
            ),
            "similarity": sim,
        }
        for sim, uid in top
        if uid in match_profiles
    ]

    # ── Amplify (Mechanism 1): re-rank this page by blended taste ───────────────
    # persistent (DB) + module session + global session, confidence-gated. Each
    # candidate is nudged by its hottest session-active commodity. This reorders
    # the already-fetched page only; a larger-pool re-rank is a future step.
    try:
        weights = get_amplify_weights(repo.session, r, profile.id, _MODULE)
        if weights:
            results.sort(
                key=lambda res: res["similarity"] * commodity_boost(
                    weights, commodity_ids_for(repo.session, res.get("commodity", []))
                ),
                reverse=True,
            )
    except Exception:
        log.exception("amplify re-rank failed for profile %s; serving unranked order", profile.id)

    return {
        "user_id":         str(user_id),
        "role":            role_str,
        "commodity":       commodity_names,
        "qty_range":       f"{int(profile.quantity_min)}–{int(profile.quantity_max)}mt",
        "page":            page,
        "limit":           limit,
        "total_available": total_available,
        "has_more":        (offset + len(results)) < total_available,
        "total":           len(results),
        "results":         results,
    }


def custom_recommendation_search(
    repo: IConnectionsRepository,
    commodity: list[str],
    role: str,
    latitude_raw: float,
    longitude_raw: float,
    qty_min_mt: int,
    qty_max_mt: int,
) -> dict:
    """
    Ad-hoc vector search — no user_id needed.
    Useful for showing preview results before or during signup.
    """
    want_vec = build_query_vector(
        commodity_list=commodity,
        role=role,
        lat=latitude_raw,
        lon=longitude_raw,
        qty_min=qty_min_mt,
        qty_max=qty_max_mt,
    )

    rows = repo.ann_user_candidates_unfiltered(_to_pgvec(want_vec), limit=TOP_K)

    top = [(round(float(row["similarity"]), 4), row["user_id"]) for row in rows]

    match_profiles = repo.load_profiles_bulk([uid for _, uid in top])
    results = [
        {**fmt_profile(match_profiles[uid]), "similarity": sim}
        for sim, uid in top
        if uid in match_profiles
    ]
    return {"total": len(results), "results": results}
