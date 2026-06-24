"""
Connections module — HTTP layer (thin wrappers only, zero business logic).

Two sub-routers:
  connections_router      /connections/...
  recommendations_router  /recommendations/...

Identity is derived from the Bearer token via get_current_user_id — never
from client-supplied path or query params.
"""
from uuid import UUID

import redis as redis_lib
from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.core.redis_client import get_redis
from app.dependencies import get_current_user_id, get_db
from app.modules.connections.schemas import MessageRequestCreate, SearchPayload, SeenPayload
from app.modules.connections import service
from app.shared.utils.response import ok


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Connections router   /connections/...
# ═══════════════════════════════════════════════════════════════════════════════

connections_router = APIRouter(prefix="/connections", tags=["connections"])


# ── Search suggestions (public — register BEFORE parameterised routes) ─────────

@connections_router.get("/search/suggestions")
def suggestions(
    q: str = Query(..., min_length=2),
    db: Session = Depends(get_db),
):
    """Name / business_name prefix suggestions. Returns top 8. No auth needed."""
    results = service.search_suggestions(db, q=q)
    return ok({"total": len(results), "suggestions": results}, "Suggestions fetched")


# ── Follow ────────────────────────────────────────────────────────────────────

@connections_router.post("/follow/{target_id}", status_code=201)
def follow(
    target_id: UUID,
    me: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Follow target_id. Returns 409 if already following."""
    result = service.follow_user(db, follower_id=me, following_id=target_id)
    return ok(result, "Now following")


@connections_router.delete("/follow/{target_id}")
def unfollow(
    target_id: UUID,
    me: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Unfollow target_id. Returns 404 if not currently following."""
    result = service.unfollow_user(db, follower_id=me, following_id=target_id)
    return ok(result, "Unfollowed")


@connections_router.get("/follow/status/{target_id}")
def follow_status(
    target_id: UUID,
    me: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Am I following this person? Drives Follow / Unfollow button state."""
    following = service.is_following(db, me=me, target=target_id)
    return ok({"following": following}, "Follow status fetched")


# Public — viewing any user's social graph

@connections_router.get("/{user_id}/followers")
def list_followers(
    user_id: UUID,
    db: Session = Depends(get_db),
):
    """Everyone who follows user_id (public)."""
    followers = service.get_followers(db, user_id)
    return ok({"total": len(followers), "followers": followers}, "Followers fetched")


@connections_router.get("/{user_id}/following")
def list_following(
    user_id: UUID,
    db: Session = Depends(get_db),
):
    """Everyone user_id follows (public)."""
    following = service.get_following(db, user_id)
    return ok({"total": len(following), "following": following}, "Following fetched")


# ── Message Requests ──────────────────────────────────────────────────────────

@connections_router.post("/message-request/{target_id}", status_code=201)
def send_request(
    target_id: UUID,
    payload: MessageRequestCreate | None = None,
    me: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Send a message request to target_id. Returns 409 if one already exists.
    An optional `first_message` becomes the opening line of the DM once accepted."""
    result = service.send_message_request(
        db,
        sender_id=me,
        receiver_id=target_id,
        first_message=payload.first_message if payload else None,
    )
    return ok(result, "Message request sent")


@connections_router.delete("/message-request/{target_id}")
def withdraw_request(
    target_id: UUID,
    me: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Withdraw a pending message request. Returns 404 if no pending request."""
    result = service.withdraw_message_request(db, sender_id=me, receiver_id=target_id)
    return ok(result, "Request withdrawn")


@connections_router.patch("/message-request/{request_id}/accept")
def accept_request(
    request_id: int,
    background_tasks: BackgroundTasks,
    me: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Accept a message request. Only the receiver can accept.
    Activates the DM conversation and notifies the original sender in real time."""
    # Local import keeps the chat-module dependency contained (avoids an import cycle).
    from app.modules.chat.presentation.connection_manager import emit_to_user

    result = service.respond_to_request(db, request_id=request_id, me=me, action="accepted")
    background_tasks.add_task(
        emit_to_user,
        UUID(result["sender_id"]),
        "message_request_accepted",
        {
            "request_id": result["id"],
            "conversation_id": result.get("conversation_id"),
            "accepted_by": str(me),
        },
    )
    return ok(result, "Request accepted")


@connections_router.patch("/message-request/{request_id}/decline")
def decline_request(
    request_id: int,
    background_tasks: BackgroundTasks,
    me: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Decline a message request. Only the receiver can decline.
    Non-permanent — the sender can re-send later, which reopens it as pending."""
    # Local import keeps the chat-module dependency contained (avoids an import cycle).
    from app.modules.chat.presentation.connection_manager import emit_to_user

    result = service.respond_to_request(db, request_id=request_id, me=me, action="declined")
    background_tasks.add_task(
        emit_to_user,
        UUID(result["sender_id"]),
        "message_request_declined",
        {"request_id": result["id"], "declined_by": str(me)},
    )
    return ok(result, "Request declined")


@connections_router.get("/message-requests/received")
def received_requests(
    me: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Pending message requests waiting on me to accept or decline."""
    requests = service.get_received_requests(db, me=me)
    return ok({"total": len(requests), "requests": requests}, "Received requests fetched")


@connections_router.get("/message-requests/sent")
def sent_requests(
    me: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """All message requests I have sent, across all statuses."""
    requests = service.get_sent_requests(db, me=me)
    return ok({"total": len(requests), "requests": requests}, "Sent requests fetched")


# ── Share recipients ──────────────────────────────────────────────────────────

@connections_router.get("/share-recipients")
def get_share_recipients(
    me: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Returns DM connections and groups the current user can forward content to.
    Used by both post and news share sheets — call once, reuse the result for
    either share flow.
    """
    from app.modules.chat.data.repository import ChatRepository
    result = ChatRepository(db).get_share_recipients(me)
    return ok(result, "Share recipients fetched")


# ── Search ────────────────────────────────────────────────────────────────────

@connections_router.get("/search")
def search(
    me: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    q:             str | None = Query(default=None, description="Partial match on name or business name"),
    role:          str | None = Query(default=None, description="trader | broker | exporter"),
    commodity:     str | None = Query(default=None, description="Partial match on commodity name"),
    city:          str | None = Query(default=None, description="Partial match on city"),
    user_verified_only:     bool       = Query(default=False, description="Only return KYC-verified users"),
    business_verified_only: bool       = Query(default=False, description="Only return KYB-verified users"),
    page:          int        = Query(default=1, ge=1),
    limit:         int        = Query(default=20, ge=1, le=100),
):
    """Filtered user search. Me is excluded from results. All query params optional."""
    result = service.search_users(
        db, me=me, q=q, role=role, commodity=commodity,
        city=city, user_verified_only=user_verified_only,
        business_verified_only=business_verified_only, page=page, limit=limit,
    )
    return ok(result, "Search results fetched")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Recommendations router   /recommendations/...
# ═══════════════════════════════════════════════════════════════════════════════

recommendations_router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@recommendations_router.get("/")
def get_recommendations(
    me: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    r: redis_lib.Redis = Depends(get_redis),
    page:  int = Query(default=1,  ge=1,         description="Page number (1-based)"),
    limit: int = Query(default=20, ge=1, le=100, description="Results per page"),
):
    """Paginated user matches based on my profile (commodity, role, location, quantity)."""
    result = service.get_recommendations(db, r, user_id=me, page=page, limit=limit)
    return ok(result, "Recommendations fetched")


@recommendations_router.delete("/seen", status_code=204)
def clear_seen(
    me: UUID = Depends(get_current_user_id),
    r: redis_lib.Redis = Depends(get_redis),
):
    """Clear the calling user's seen set — all recommendations resurface immediately."""
    service.clear_recommendations_seen(r, user_id=me)


@recommendations_router.post("/seen", status_code=204)
def mark_seen(
    payload: SeenPayload,
    me: UUID = Depends(get_current_user_id),
    r: redis_lib.Redis = Depends(get_redis),
):
    """
    Mark recommendation cards as seen. Excluded from future GET /recommendations
    for 48 hours from the first call, then the seen set auto-expires.
    Best-effort — client does not retry on failure.
    """
    service.mark_recommendations_seen(r, user_id=me, seen_user_ids=payload.user_ids)


@recommendations_router.post("/search")
def custom_search(
    payload: SearchPayload,
    db: Session = Depends(get_db),
):
    """Ad-hoc vector search with a custom payload — no auth needed."""
    result = service.custom_recommendation_search(
        db,
        commodity=payload.commodity,
        role=payload.role,
        latitude_raw=payload.latitude_raw,
        longitude_raw=payload.longitude_raw,
        qty_min_mt=payload.qty_min_mt,
        qty_max_mt=payload.qty_max_mt,
    )
    return ok(result, "Search results fetched")
