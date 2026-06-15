"""
Connections service layer — all business + DB logic, zero FastAPI imports.

Sections:
  A. Follow graph       (user_connections — UUID FK → users.id)
  B. Message requests   (message_requests — UUID FK → users.id)
  C. User search        (profile + profile_commodities + commodities + roles)
  D. Recommendations    (user_embeddings pgvector — HNSW cosine ANN via <=>)
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import cast
from uuid import UUID, uuid4

import redis as redis_lib
from fastapi import HTTPException
from sqlalchemy import and_, text
from sqlalchemy.orm import Session, aliased, joinedload

from app.modules.connections.models import MessageRequest, UserConnection
from app.modules.profile.models import (
    Business,
    Commodity,
    Profile,
    Profile_Commodity,
    Role,
)
from app.modules.connections.encoding.vector import build_query_vector
from app.modules.connections.weights_config import ALL_COMMODITIES

TOP_K = 20
_SEEN_TTL = 172_800  # 48 hours — set once at key creation, never reset

# role_id (int) → lowercase string used by the vector encoder
_ROLE_ID_TO_NAME = {1: "trader", 2: "broker", 3: "exporter"}

# ── Search intent parsing ────────────────────────────────────────────────────
_KNOWN_ROLES = {"trader", "broker", "exporter"}
_ROLE_PLURAL = {"traders": "trader", "brokers": "broker", "exporters": "exporter"}
_KNOWN_COMMODITIES = set(ALL_COMMODITIES)
_CITY_PATTERN = re.compile(r'\b(?:in|from)\s+(\w+)', re.IGNORECASE)


def _parse_search_intent(q: str) -> dict:
    """
    Extracts role, commodity, city from free-text q so the frontend only needs
    one search box. Explicit params passed by the caller always take priority.

    "rice exporters in mumbai" → role="exporter", commodity="rice", city="mumbai", name_q=None
    "ravi broker"              → role="broker", commodity=None, city=None, name_q="ravi"
    """
    tokens = q.lower().split()
    role, commodity, city = None, None, None
    skip: set[str] = set()

    city_match = _CITY_PATTERN.search(q)
    if city_match:
        city = city_match.group(1).lower()
        skip.update(city_match.group(0).lower().split())

    remaining = []
    for token in tokens:
        if token in skip:
            continue
        normalized = _ROLE_PLURAL.get(token, token)
        if normalized in _KNOWN_ROLES:
            role = normalized
        elif token in _KNOWN_COMMODITIES:
            commodity = token
        else:
            remaining.append(token)

    return {
        "role":      role,
        "commodity": commodity,
        "city":      city,
        "name_q":    " ".join(remaining) or None,
    }


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


def _fmt_profile(
    profile: Profile,
    *,
    msg_req_status: str | None = None,
    follow_status: bool = False,
) -> dict:
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
        "msg_req_status":       msg_req_status,
        "follow_status":        follow_status,
    }


def _bulk_statuses(db: Session, me: UUID, target_ids: list[UUID]) -> dict:
    """
    Returns {uid: {"msg_req_status": str|None, "follow_status": bool}}
    for each target in two queries (one for msg requests, one for follows).
    """
    if not target_ids:
        return {}
    msg_reqs = db.query(MessageRequest).filter(
        MessageRequest.sender_id == me,
        MessageRequest.receiver_id.in_(target_ids),
    ).all()
    msg_req_map = {r.receiver_id: r.status for r in msg_reqs}

    follows = db.query(UserConnection).filter(
        UserConnection.follower_id == me,
        UserConnection.following_id.in_(target_ids),
    ).all()
    follow_set = {f.following_id for f in follows}

    return {
        uid: {
            "msg_req_status": msg_req_map.get(uid),
            "follow_status":  uid in follow_set,
        }
        for uid in target_ids
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
    """
    One-directional unfollow:
      - removes the caller's follow edge (follower → following) and adjusts counts
      - deletes the caller's own outgoing message request to that user, if any
    The other person's follow-back, their request to the caller, and any shared
    DM conversation are left untouched.
    """
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

    # void only the caller's own outgoing message request to this user
    db.query(MessageRequest).filter(
        MessageRequest.sender_id == follower_id,
        MessageRequest.receiver_id == following_id,
    ).delete(synchronize_session=False)

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

def send_message_request(
    db: Session,
    sender_id: UUID,
    receiver_id: UUID,
    first_message: str | None = None,
) -> dict:
    if sender_id == receiver_id:
        raise HTTPException(status_code=400, detail="Cannot send a request to yourself.")
    existing = db.query(MessageRequest).filter(
        MessageRequest.sender_id == sender_id,
        MessageRequest.receiver_id == receiver_id,
    ).first()
    if existing:
        if existing.status == "declined":
            # un-stick a previously declined request — reopen it as a fresh pending request
            existing.status = "pending"
            existing.sent_at = datetime.now(timezone.utc)
            existing.acted_at = None
            existing.first_message = first_message
            db.commit()
            db.refresh(existing)
            return {"id": existing.id, "status": existing.status, "sent_at": existing.sent_at}
        if existing.status == "accepted":
            raise HTTPException(status_code=409, detail="You are already connected with this user.")
        raise HTTPException(status_code=409, detail="Message request already sent.")
    req = MessageRequest(sender_id=sender_id, receiver_id=receiver_id, first_message=first_message)
    db.add(req)
    db.commit()
    db.refresh(req)
    return {"id": req.id, "status": req.status, "sent_at": req.sent_at}


def withdraw_message_request(db: Session, sender_id: UUID, receiver_id: UUID) -> dict:
    req = db.query(MessageRequest).filter(
        MessageRequest.sender_id == sender_id,
        MessageRequest.receiver_id == receiver_id,
        MessageRequest.status.in_(["pending", "declined"]),
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="No pending or declined request found to withdraw.")
    db.delete(req)
    db.commit()
    return {"status": "withdrawn", "receiver_id": str(receiver_id)}


def respond_to_request(db: Session, request_id: int, me: UUID, action: str) -> dict:
    """action must be 'accepted' or 'declined'. Only the receiver can call this.

    On 'accepted', the DM conversation between the two users is created (or, if one
    already exists, reactivated) with status 'active' — the message request is the
    consent, so both sides can chat immediately afterwards.
    """
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

    conv_id = None
    if action == "accepted":
        conv_id = _activate_dm(db, initiator_id=req.sender_id, other_id=req.receiver_id)
        # Seed the request's opening line as the first message of the conversation,
        # in the same transaction so the DM is never observed empty after accept.
        if req.first_message:
            _seed_first_message(db, conv_id, sender_id=req.sender_id, body=req.first_message)

    db.commit()
    result = {"id": request_id, "status": action, "sender_id": str(req.sender_id)}
    if conv_id is not None:
        result["conversation_id"] = str(conv_id)
    return result


def _seed_first_message(db: Session, conv_id: UUID, sender_id: UUID, body: str) -> None:
    """Insert the request's opening line as the first DM message. Does not commit —
    the caller owns the transaction."""
    from app.modules.chat.data.models import Message

    now = datetime.now(timezone.utc)
    db.add(Message(
        id=uuid4(),
        context_type="dm",
        context_id=conv_id,
        sender_id=sender_id,
        message_type="text",
        body=body,
        is_deleted=False,
        sent_at=now,
    ))


def _activate_dm(db: Session, initiator_id: UUID, other_id: UUID) -> UUID:
    """Create or reactivate the DM conversation between two users and return its id.
    The request sender is recorded as the conversation initiator. Does not commit —
    the caller owns the transaction."""
    # Local import keeps the chat-module dependency contained (avoids an import cycle).
    from app.modules.chat.data.models import Conversation, ConversationMember
    from app.modules.chat.domain.entities import ConvStatus

    cm_a = aliased(ConversationMember)
    cm_b = aliased(ConversationMember)
    conv = (
        db.query(Conversation)
        .join(cm_a, and_(cm_a.conversation_id == Conversation.id, cm_a.user_id == initiator_id))
        .join(cm_b, and_(cm_b.conversation_id == Conversation.id, cm_b.user_id == other_id))
        .filter(Conversation.type == "dm")
        .first()
    )

    now = datetime.now(timezone.utc)
    if conv is None:
        conv = Conversation(
            id=uuid4(), type="dm", status=ConvStatus.ACTIVE,
            initiator_id=initiator_id, created_at=now, updated_at=now,
        )
        db.add(conv)
        db.flush()  # populate conv.id
        db.add(ConversationMember(conversation_id=conv.id, user_id=initiator_id, joined_at=now))
        db.add(ConversationMember(conversation_id=conv.id, user_id=other_id, joined_at=now))
    else:
        conv.status = ConvStatus.ACTIVE
        conv.updated_at = now

    return conv.id


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
        {
            "request_id": r.id,
            "from": _fmt_profile(profiles[r.sender_id]),
            "first_message": r.first_message,
            "sent_at": r.sent_at,
        }
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
            "request_id":    r.id,
            "to":            _fmt_profile(profiles[r.receiver_id]),
            "status":        r.status,
            "first_message": r.first_message,
            "sent_at":       r.sent_at,
            "acted_at":      r.acted_at,
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
    if q and not any([role, commodity, city]):
        intent = _parse_search_intent(q)
        role      = role      or intent["role"]
        commodity = commodity or intent["commodity"]
        city      = city      or intent["city"]
        q         = intent["name_q"]

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
    statuses = _bulk_statuses(db, me, [p.users_id for p in profiles])
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "results": [
            _fmt_profile(
                p,
                msg_req_status=statuses.get(p.users_id, {}).get("msg_req_status"),
                follow_status=statuses.get(p.users_id, {}).get("follow_status", False),
            )
            for p in profiles
        ],
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

def clear_recommendations_seen(r: redis_lib.Redis, user_id: UUID) -> None:
    """Delete the user's seen set so all recommendations resurface immediately."""
    try:
        r.delete(f"rec:seen:{user_id}")
    except Exception:
        pass


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
        # redis-py types sync returns as possibly-awaitable (ResponseT); cast to the
        # concrete set the sync client actually returns so the type checker is happy.
        raw = cast(set, r.smembers(f"rec:seen:{user_id}"))
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

    match_ids = [uid for _, uid in top]
    match_profiles = _load_profiles_bulk(db, match_ids)
    statuses = _bulk_statuses(db, user_id, match_ids)
    results = [
        {
            **_fmt_profile(
                match_profiles[uid],
                msg_req_status=statuses.get(uid, {}).get("msg_req_status"),
                follow_status=statuses.get(uid, {}).get("follow_status", False),
            ),
            "similarity": sim,
        }
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
