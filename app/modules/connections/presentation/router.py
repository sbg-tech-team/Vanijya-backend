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
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from app.core.redis_client import get_redis
from app.modules.connections.domain.interfaces.repository import IConnectionsRepository
from app.modules.chat.presentation.dependencies import get_share_recipients_uc
from app.modules.connections.presentation.dependencies import get_connections_repo
from app.dependencies import CurrentUser, get_current_user, get_current_user_id
from app.modules.connections.presentation.schemas import (
    FollowCreate,
    MessageRequestCreate,
    ProfileViewSignal,
    SearchPayload,
    SeenPayload,
)
from app.modules.connections.application import service
from app.modules.connections.domain.exceptions import (
    AlreadyConnectedError,
    AlreadyFollowingError,
    ConversationBlockedError,
    MessageRequestAlreadySentError,
    MessageRequestNotFoundError,
    NoPendingRequestError,
    NotFollowingError,
    ProfileNotFoundError,
    SelfFollowError,
    SelfRequestError,
)
from app.shared.utils.response import ok


def _translate(exc: Exception) -> HTTPException:
    """Map domain exceptions to the exact HTTP status codes and detail strings V1 used."""
    mapping = {
        SelfFollowError:                (400, "Cannot follow yourself."),
        AlreadyFollowingError:          (409, "Already following this user."),
        NotFollowingError:              (404, "You are not following this user."),
        SelfRequestError:               (400, "Cannot send a request to yourself."),
        AlreadyConnectedError:          (409, "You are already connected with this user."),
        MessageRequestAlreadySentError: (409, "Message request already sent."),
        NoPendingRequestError:          (404, "No pending or declined request found to withdraw."),
        MessageRequestNotFoundError:    (404, "Request not found, already acted on, or you are not the receiver."),
        ConversationBlockedError:       (403, "This conversation is blocked."),
        ProfileNotFoundError:           (404, "Profile not found — complete onboarding first"),
    }
    status, detail = mapping.get(type(exc), (500, "Internal Server Error"))
    return HTTPException(status_code=status, detail=detail)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Connections router   /connections/...
# ═══════════════════════════════════════════════════════════════════════════════

connections_router = APIRouter(prefix="/connections", tags=["connections"])


# ── Search suggestions (public — register BEFORE parameterised routes) ─────────

@connections_router.get("/search/suggestions")
def suggestions(
    q: str = Query(..., min_length=2),
    repo: IConnectionsRepository = Depends(get_connections_repo),
):
    """Name / business_name prefix suggestions. Returns top 8. No auth needed."""
    results = service.search_suggestions(repo, q=q)
    return ok({"total": len(results), "suggestions": results}, "Suggestions fetched")


# ── Follow ────────────────────────────────────────────────────────────────────

@connections_router.post("/follow/{target_id}", status_code=201)
def follow(
    target_id: UUID,
    payload: FollowCreate | None = None,
    user: CurrentUser = Depends(get_current_user),
    repo: IConnectionsRepository = Depends(get_connections_repo),
    r: redis_lib.Redis = Depends(get_redis),
):
    """Follow target_id. Returns 409 if already following.
    Optional body carries the target's commodity_ids/role_id for the taste signal."""
    try:
        result = service.follow_user(
            repo,
            follower_id=user.user_id,
            following_id=target_id,
            rc=r,
            actor_profile_id=user.profile_id,
            commodity_ids=payload.commodity_ids if payload else [],
            role_id=payload.role_id if payload else None,
        )
    except Exception as exc:
        raise _translate(exc) from exc
    return ok(result, "Now following")


@connections_router.delete("/follow/{target_id}")
def unfollow(
    target_id: UUID,
    me: UUID = Depends(get_current_user_id),
    repo: IConnectionsRepository = Depends(get_connections_repo),
):
    """Unfollow target_id. Returns 404 if not currently following."""
    try:
        result = service.unfollow_user(repo, follower_id=me, following_id=target_id)
    except Exception as exc:
        raise _translate(exc) from exc
    return ok(result, "Unfollowed")


@connections_router.get("/follow/status/{target_id}")
def follow_status(
    target_id: UUID,
    me: UUID = Depends(get_current_user_id),
    repo: IConnectionsRepository = Depends(get_connections_repo),
):
    """Am I following this person? Drives Follow / Unfollow button state."""
    following = service.is_following(repo, me=me, target=target_id)
    return ok({"following": following}, "Follow status fetched")


# Any user's social graph, visible to signed-in users.
#
# These were the only reads in the app that answered without a token, while
# /profile/{profile_id} right next to them required one — so the profile was
# private but that same person's whole follower list was not. Combined with
# /share/user/{profile_id}, whose id is sequential, that allowed an anonymous
# crawl of the user base and the graph.

@connections_router.get("/{user_id}/followers")
def list_followers(
    user_id: UUID,
    _viewer: UUID = Depends(get_current_user_id),
    repo: IConnectionsRepository = Depends(get_connections_repo),
):
    """Everyone who follows user_id. Any signed-in user may look."""
    followers = service.get_followers(repo, user_id)
    return ok({"total": len(followers), "followers": followers}, "Followers fetched")


@connections_router.get("/{user_id}/following")
def list_following(
    user_id: UUID,
    _viewer: UUID = Depends(get_current_user_id),
    repo: IConnectionsRepository = Depends(get_connections_repo),
):
    """Everyone user_id follows. Any signed-in user may look."""
    following = service.get_following(repo, user_id)
    return ok({"total": len(following), "following": following}, "Following fetched")


# ── Message Requests ──────────────────────────────────────────────────────────

@connections_router.post("/message-request/{target_id}", status_code=201)
def send_request(
    target_id: UUID,
    payload: MessageRequestCreate | None = None,
    user: CurrentUser = Depends(get_current_user),
    repo: IConnectionsRepository = Depends(get_connections_repo),
    r: redis_lib.Redis = Depends(get_redis),
):
    """Send a message request to target_id. Returns 409 if one already exists.
    An optional `first_message` becomes the opening line of the DM once accepted.
    Optional commodity_ids/role_id carry the target's taste dimensions."""
    try:
        result = service.send_message_request(
            repo,
            sender_id=user.user_id,
            receiver_id=target_id,
            first_message=payload.first_message if payload else None,
            rc=r,
            actor_profile_id=user.profile_id,
            commodity_ids=payload.commodity_ids if payload else [],
            role_id=payload.role_id if payload else None,
        )
    except Exception as exc:
        raise _translate(exc) from exc
    return ok(result, "Message request sent")


@connections_router.delete("/message-request/{target_id}")
def withdraw_request(
    target_id: UUID,
    me: UUID = Depends(get_current_user_id),
    repo: IConnectionsRepository = Depends(get_connections_repo),
):
    """Withdraw a pending message request. Returns 404 if no pending request."""
    try:
        result = service.withdraw_message_request(repo, sender_id=me, receiver_id=target_id)
    except Exception as exc:
        raise _translate(exc) from exc
    return ok(result, "Request withdrawn")


@connections_router.patch("/message-request/{request_id}/accept")
def accept_request(
    request_id: int,
    background_tasks: BackgroundTasks,
    me: UUID = Depends(get_current_user_id),
    repo: IConnectionsRepository = Depends(get_connections_repo),
):
    """Accept a message request. Only the receiver can accept.
    Activates the DM conversation and notifies the original sender in real time."""
    # Local import keeps the chat-module dependency contained (avoids an import cycle).
    from app.core.realtime import emit_to_user

    try:
        result = service.respond_to_request(repo, request_id=request_id, me=me, action="accepted")
    except Exception as exc:
        raise _translate(exc) from exc
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
    repo: IConnectionsRepository = Depends(get_connections_repo),
):
    """Decline a message request. Only the receiver can decline.
    Non-permanent — the sender can re-send later, which reopens it as pending."""
    # Local import keeps the chat-module dependency contained (avoids an import cycle).
    from app.core.realtime import emit_to_user

    try:
        result = service.respond_to_request(repo, request_id=request_id, me=me, action="declined")
    except Exception as exc:
        raise _translate(exc) from exc
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
    repo: IConnectionsRepository = Depends(get_connections_repo),
):
    """Pending message requests waiting on me to accept or decline."""
    requests = service.get_received_requests(repo, me=me)
    return ok({"total": len(requests), "requests": requests}, "Received requests fetched")


@connections_router.get("/message-requests/sent")
def sent_requests(
    me: UUID = Depends(get_current_user_id),
    repo: IConnectionsRepository = Depends(get_connections_repo),
):
    """All message requests I have sent, across all statuses."""
    requests = service.get_sent_requests(repo, me=me)
    return ok({"total": len(requests), "requests": requests}, "Sent requests fetched")


# ── Search ────────────────────────────────────────────────────────────────────

@connections_router.get("/search")
def search(
    me: UUID = Depends(get_current_user_id),
    repo: IConnectionsRepository = Depends(get_connections_repo),
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
        repo, me=me, q=q, role=role, commodity=commodity,
        city=city, user_verified_only=user_verified_only,
        business_verified_only=business_verified_only, page=page, limit=limit,
    )
    return ok(result, "Search results fetched")


@connections_router.get("/share-recipients")
def get_share_recipients(
    me: UUID = Depends(get_current_user_id),
    share_uc=Depends(get_share_recipients_uc),
):
    """
    Returns DM connections and groups the current user can forward content to.
    Used by both post and news share sheets — call once, reuse the result for
    either share flow.
    """
    # chat owns this data — go through its use case, not its repository
    result = share_uc.execute(me)
    return ok(result, "Share recipients fetched")


@connections_router.post("/view", status_code=204)
def record_view(
    payload: ProfileViewSignal,
    user: CurrentUser = Depends(get_current_user),
    r: redis_lib.Redis = Depends(get_redis),
):
    """Fire when the user opens a profile card. Records a mild taste signal for the
    viewed profile's commodities. Best-effort — never fails the request."""
    if payload.target_id == user.user_id:
        return  # ignore self-views
    service.record_profile_view(
        r,
        viewer_profile_id=user.profile_id,
        commodity_ids=payload.commodity_ids,
        role_id=payload.role_id,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Recommendations router   /recommendations/...
# ═══════════════════════════════════════════════════════════════════════════════

recommendations_router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@recommendations_router.get("/")
def get_recommendations(
    me: UUID = Depends(get_current_user_id),
    repo: IConnectionsRepository = Depends(get_connections_repo),
    r: redis_lib.Redis = Depends(get_redis),
    page:  int = Query(default=1,  ge=1,         description="Page number (1-based)"),
    limit: int = Query(default=20, ge=1, le=100, description="Results per page"),
):
    """Paginated user matches based on my profile (commodity, role, location, quantity)."""
    try:
        result = service.get_recommendations(repo, r, user_id=me, page=page, limit=limit)
    except Exception as exc:
        raise _translate(exc) from exc
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
    repo: IConnectionsRepository = Depends(get_connections_repo),
):
    """Ad-hoc vector search with a custom payload — no auth needed."""
    result = service.custom_recommendation_search(
        repo,
        commodity=payload.commodity,
        role=payload.role,
        latitude_raw=payload.latitude_raw,
        longitude_raw=payload.longitude_raw,
        qty_min_mt=payload.qty_min_mt,
        qty_max_mt=payload.qty_max_mt,
    )
    return ok(result, "Search results fetched")
