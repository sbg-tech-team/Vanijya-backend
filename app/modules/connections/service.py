"""
Connections service layer — all business + DB logic, zero FastAPI imports.

Sections:
  A. Follow graph       (user_connections — UUID FK → users.id)
  B. Message requests   (message_requests — UUID FK → users.id)
  C. User search        (profile + profile_commodities + commodities + roles)
  D. Recommendations    (user_embeddings pgvector — HNSW cosine ANN via <=>)
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import redis as redis_lib
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session, joinedload

from app.modules.connections.models import MessageRequest, UserConnection
from app.modules.profile.models import (
    Business,
    Commodity,
    Profile,
    Profile_Commodity,
    Role,
)
from app.modules.connections.encoding.vector import build_query_vector

TOP_K = 20
_SEEN_TTL = 172_800  # 48 hours — set once at key creation, never reset

# role_id (int) → lowercase string used by the vector encoder
_ROLE_ID_TO_NAME = {1: "trader", 2: "broker", 3: "exporter"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_profile(db: Session, user_id: UUID) -> Profile | None:
    """Load a profile with role + commodities + business in one query."""
    return (
        db.query(Profile)
        .options(
            joinedload(Profile.role),
            joinedload(Profile.business),
            joinedload(Profile.commodities).joinedload(Profile_Commodity.commodity),
        )
        .filter(Profile.users_id == user_id)
        .first()
    )


def _load_profiles_bulk(db: Session, user_ids: list[UUID]) -> dict[UUID, Profile]:
    """Load multiple profiles in a single query. Returns {users_id: Profile}."""
    if not user_ids:
        return {}
    rows = (
        db.query(Profile)
        .options(
            joinedload(Profile.role),
            joinedload(Profile.business),
            joinedload(Profile.commodities).joinedload(Profile_Commodity.commodity),
        )
        .filter(Profile.users_id.in_(user_ids))
        .all()
    )
    return {p.users_id: p for p in rows}


def _fmt_profile(profile: Profile) -> dict:
    """Serialize a Profile into a flat dict for connection list responses."""
    return {
        "user_id":              str(profile.users_id),
        "name":                 profile.name,
        "avatar_url":           profile.avatar_url,
        "role":                 profile.role.name.lower() if profile.role else None,
        "commodity":            [pc.commodity.name.lower() for pc in profile.commodities],
        "is_user_verified":     profile.is_user_verified,
        "is_business_verified": profile.is_business_verified,
        "quantity_min":         int(profile.quantity_min),
        "quantity_max":         int(profile.quantity_max),
        "business_name":        profile.business.business_name,
        "city":                 profile.business.city,
        "state":                profile.business.state,
    }


def _to_pgvec(vec: list[float]) -> str:
    """Format a Python float list as a pgvector literal: '[v1,v2,...]'"""
    return "[" + ",".join(str(v) for v in vec) + "]"


# ---------------------------------------------------------------------------
# A. Follow graph
# ---------------------------------------------------------------------------

def follow_user(db: Session, follower_id: UUID, following_id: UUID) -> dict:
    if follower_id == following_id:
        raise HTTPException(status_code=400, detail="Cannot follow yourself.")
    existing = db.query(UserConnection).filter(
        UserConnection.follower_id == follower_id,
        UserConnection.following_id == following_id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Already following this user.")
    db.add(UserConnection(follower_id=follower_id, following_id=following_id))
    # increment following_count on the follower's profile
    db.query(Profile).filter(Profile.users_id == follower_id).update(
        {"following_count": Profile.following_count + 1}
    )
    # increment followers_count on the target's profile
    db.query(Profile).filter(Profile.users_id == following_id).update(
        {"followers_count": Profile.followers_count + 1}
    )
    db.commit()
    return {"status": "following", "following_id": str(following_id)}


def unfollow_user(db: Session, follower_id: UUID, following_id: UUID) -> dict:
    conn = db.query(UserConnection).filter(
        UserConnection.follower_id == follower_id,
        UserConnection.following_id == following_id,
    ).first()
    if not conn:
        raise HTTPException(status_code=404, detail="You are not following this user.")
    db.delete(conn)
    # decrement following_count on the follower's profile (floor at 0)
    db.query(Profile).filter(
        Profile.users_id == follower_id, Profile.following_count > 0
    ).update({"following_count": Profile.following_count - 1})
    # decrement followers_count on the target's profile (floor at 0)
    db.query(Profile).filter(
        Profile.users_id == following_id, Profile.followers_count > 0
    ).update({"followers_count": Profile.followers_count - 1})
    db.commit()
    return {"status": "unfollowed", "following_id": str(following_id)}


def get_followers(db: Session, user_id: UUID) -> list[dict]:
    conns = (
        db.query(UserConnection)
        .filter(UserConnection.following_id == user_id)
        .order_by(UserConnection.followed_at.desc())
        .all()
    )
    profiles = _load_profiles_bulk(db, [c.follower_id for c in conns])
    result = []
    for conn in conns:
        p = profiles.get(conn.follower_id)
        if p:
            result.append({**_fmt_profile(p), "followed_at": conn.followed_at})
    return result


def get_following(db: Session, user_id: UUID) -> list[dict]:
    conns = (
        db.query(UserConnection)
        .filter(UserConnection.follower_id == user_id)
        .order_by(UserConnection.followed_at.desc())
        .all()
    )
    profiles = _load_profiles_bulk(db, [c.following_id for c in conns])
    result = []
    for conn in conns:
        p = profiles.get(conn.following_id)
        if p:
            result.append({**_fmt_profile(p), "followed_at": conn.followed_at})
    return result


def is_following(db: Session, me: UUID, target: UUID) -> bool:
    return (
        db.query(UserConnection)
        .filter(
            UserConnection.follower_id == me,
            UserConnection.following_id == target,
        )
        .first()
    ) is not None


# ---------------------------------------------------------------------------
# B. Message requests
# ---------------------------------------------------------------------------

def send_message_request(db: Session, sender_id: UUID, receiver_id: UUID) -> dict:
    if sender_id == receiver_id:
        raise HTTPException(status_code=400, detail="Cannot send a request to yourself.")
    existing = db.query(MessageRequest).filter(
        MessageRequest.sender_id == sender_id,
        MessageRequest.receiver_id == receiver_id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Message request already sent.")
    req = MessageRequest(sender_id=sender_id, receiver_id=receiver_id)
    db.add(req)
    db.commit()
    db.refresh(req)
    return {"id": req.id, "status": req.status, "sent_at": req.sent_at}


def withdraw_message_request(db: Session, sender_id: UUID, receiver_id: UUID) -> dict:
    req = db.query(MessageRequest).filter(
        MessageRequest.sender_id == sender_id,
        MessageRequest.receiver_id == receiver_id,
        MessageRequest.status == "pending",
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="No pending request found to withdraw.")
    db.delete(req)
    db.commit()
    return {"status": "withdrawn", "receiver_id": str(receiver_id)}


def respond_to_request(db: Session, request_id: int, me: UUID, action: str) -> dict:
    """action must be 'accepted' or 'declined'. Only the receiver can call this."""
    req = db.query(MessageRequest).filter(
        MessageRequest.id == request_id,
        MessageRequest.receiver_id == me,
        MessageRequest.status == "pending",
    ).first()
    if not req:
        raise HTTPException(
            status_code=404,
            detail="Request not found, already acted on, or you are not the receiver.",
        )
    req.status = action
    req.acted_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": request_id, "status": action}


def get_received_requests(db: Session, me: UUID) -> list[dict]:
    """Pending inbox — requests waiting on me to accept or decline."""
    reqs = (
        db.query(MessageRequest)
        .filter(MessageRequest.receiver_id == me, MessageRequest.status == "pending")
        .order_by(MessageRequest.sent_at.desc())
        .all()
    )
    profiles = _load_profiles_bulk(db, [r.sender_id for r in reqs])
    return [
        {"request_id": r.id, "from": _fmt_profile(profiles[r.sender_id]), "sent_at": r.sent_at}
        for r in reqs
        if r.sender_id in profiles
    ]


def get_sent_requests(db: Session, me: UUID) -> list[dict]:
    """All requests I have sent, all statuses."""
    reqs = (
        db.query(MessageRequest)
        .filter(MessageRequest.sender_id == me)
        .order_by(MessageRequest.sent_at.desc())
        .all()
    )
    profiles = _load_profiles_bulk(db, [r.receiver_id for r in reqs])
    return [
        {
            "request_id": r.id,
            "to":         _fmt_profile(profiles[r.receiver_id]),
            "status":     r.status,
            "sent_at":    r.sent_at,
            "acted_at":   r.acted_at,
        }
        for r in reqs
        if r.receiver_id in profiles
    ]


# ---------------------------------------------------------------------------
# C. User search  (queries profile + roles + commodities)
# ---------------------------------------------------------------------------

def search_users(
    db: Session,
    me: UUID,
    q: str | None = None,
    role: str | None = None,
    commodity: str | None = None,
    city: str | None = None,
    user_verified_only: bool = False,
    business_verified_only: bool = False,
    page: int = 1,
    limit: int = 20,
) -> dict:
    """
    Filtered user search against the real profile table.
    q                     — partial match on name / business_name
    role                  — exact match: trader | broker | exporter
    commodity             — partial match on commodity name
    city                  — partial match on city
    user_verified_only    — only return profiles where is_user_verified=True (KYC)
    business_verified_only— only return profiles where is_business_verified=True (KYB)
    Excludes the calling user. Supports pagination via page/limit.
    """
    query = (
        db.query(Profile)
        .options(
            joinedload(Profile.role),
            joinedload(Profile.commodities).joinedload(Profile_Commodity.commodity),
        )
        .filter(Profile.users_id != me)
    )

    if role:
        role_row = (
            db.query(Role)
            .filter(Role.name.ilike(role))
            .first()
        )
        if role_row:
            query = query.filter(Profile.role_id == role_row.id)
        else:
            return {"total": 0, "page": page, "limit": limit, "results": []}

    if commodity:
        query = (
            query
            .join(Profile.commodities)
            .join(Profile_Commodity.commodity)
            .filter(Commodity.name.ilike(f"%{commodity}%"))
        )

    if q:
        query = query.filter(
            Profile.name.ilike(f"%{q}%")
            | Profile.id.in_(
                db.query(Business.profile_id).filter(Business.business_name.ilike(f"%{q}%"))
            )
        )

    if city:
        query = query.filter(
            Profile.id.in_(
                db.query(Business.profile_id).filter(Business.city.ilike(f"%{city}%"))
            )
        )

    if user_verified_only:
        query = query.filter(Profile.is_user_verified == True)  # noqa: E712
    if business_verified_only:
        query = query.filter(Profile.is_business_verified == True)  # noqa: E712

    total = query.count()
    profiles = query.offset((page - 1) * limit).limit(limit).all()
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "results": [_fmt_profile(p) for p in profiles],
    }


def search_suggestions(db: Session, q: str) -> list[dict]:
    """
    Quick name / business_name suggestions. Returns top 8.
    (The old pg_trgm fuzzy match is replaced by a simpler ILIKE — same result
    for the common case without needing the trgm extension on the profile table.)
    """
    profiles = (
        db.query(Profile)
        .options(
            joinedload(Profile.role),
            joinedload(Profile.business),
            joinedload(Profile.commodities).joinedload(Profile_Commodity.commodity),
        )
        .filter(
            Profile.name.ilike(f"%{q}%")
            | Profile.id.in_(
                db.query(Business.profile_id).filter(Business.business_name.ilike(f"%{q}%"))
            )
        )
        .limit(8)
        .all()
    )
    return [_fmt_profile(p) for p in profiles]


# ---------------------------------------------------------------------------
# D. Recommendations  (pgvector HNSW cosine ANN via <=>)
# ---------------------------------------------------------------------------

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
        pass  # best-effort — frontend does not retry on failure


def _get_seen_ids(r: redis_lib.Redis, user_id: UUID) -> list[str]:
    """Fetch the seen set from Redis. Returns [] if Redis is unavailable."""
    try:
        raw = r.smembers(f"rec:seen:{user_id}")
        return [s.decode() if isinstance(s, bytes) else s for s in raw]
    except Exception:
        return []


def get_recommendations(
    db: Session,
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
    profile = _load_profile(db, user_id)
    if not profile:
        raise HTTPException(
            status_code=404,
            detail="Profile not found — complete onboarding first",
        )

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
    seen_filter = ""
    seen_params: dict = {}
    if seen_ids:
        seen_filter = "AND user_id != ALL(string_to_array(:seen_csv, ',')::uuid[])"
        seen_params["seen_csv"] = ",".join(seen_ids)

    base_exclusions = """
              AND user_id NOT IN (
                  SELECT following_id
                  FROM user_connections
                  WHERE follower_id = CAST(:uid AS uuid)
              )
              AND user_id NOT IN (
                  SELECT receiver_id
                  FROM message_requests
                  WHERE sender_id = CAST(:uid AS uuid)
              )
    """

    total_row = db.execute(
        text(f"""
            SELECT COUNT(*) AS cnt
            FROM user_embeddings
            WHERE user_id != CAST(:uid AS uuid)
              AND is_vector IS NOT NULL
              {base_exclusions}
              {seen_filter}
        """),
        {"uid": str(user_id), **seen_params},
    ).mappings().one()
    total_available = int(total_row["cnt"])

    rows = db.execute(
        text(f"""
            SELECT user_id,
                   1 - (is_vector <=> CAST(:vec AS vector)) AS similarity
            FROM user_embeddings
            WHERE user_id != CAST(:uid AS uuid)
              AND is_vector IS NOT NULL
              {base_exclusions}
              {seen_filter}
            ORDER BY is_vector <=> CAST(:vec AS vector)
            LIMIT :lim OFFSET :off
        """),
        {"vec": _to_pgvec(want_vec), "uid": str(user_id), "lim": limit, "off": offset, **seen_params},
    ).mappings().all()

    top = [(round(float(r["similarity"]), 4), r["user_id"]) for r in rows]

    match_profiles = _load_profiles_bulk(db, [uid for _, uid in top])
    results = [
        {**_fmt_profile(match_profiles[uid]), "similarity": sim}
        for sim, uid in top
        if uid in match_profiles
    ]

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
    db: Session,
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

    rows = db.execute(
        text("""
            SELECT user_id,
                   1 - (is_vector <=> CAST(:vec AS vector)) AS similarity
            FROM user_embeddings
            WHERE is_vector IS NOT NULL
            ORDER BY is_vector <=> CAST(:vec AS vector)
            LIMIT :k
        """),
        {"vec": _to_pgvec(want_vec), "k": TOP_K},
    ).mappings().all()

    top = [(round(float(r["similarity"]), 4), r["user_id"]) for r in rows]

    match_profiles = _load_profiles_bulk(db, [uid for _, uid in top])
    results = [
        {**_fmt_profile(match_profiles[uid]), "similarity": sim}
        for sim, uid in top
        if uid in match_profiles
    ]
    return {"total": len(results), "results": results}
