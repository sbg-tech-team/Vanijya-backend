# app/routes/connections.py
from fastapi import APIRouter, Depends, Query
from app.dependencies import get_current_profile_id
from app.modules.connections.db import connections as db
from app.shared.utils.response import ok

router = APIRouter(prefix="/connections", tags=["connections"])


# ─── Follow ───────────────────────────────────────────────────────────────────

@router.post("/follow/{user_id}", status_code=201)
async def follow(user_id: int, me: int = Depends(get_current_profile_id)):
    """Follow a user. Returns 409 if already following."""
    result = await db.follow_user(follower_id=me, following_id=user_id)
    return ok(result, "Now following")


@router.delete("/follow/{user_id}")
async def unfollow(user_id: int, me: int = Depends(get_current_profile_id)):
    """Unfollow a user. Returns 404 if not currently following."""
    result = await db.unfollow_user(follower_id=me, following_id=user_id)
    return ok(result, "Unfollowed")


@router.get("/followers/{user_id}")
async def list_followers(user_id: int):
    """Everyone who follows this user."""
    followers = await db.get_followers(user_id)
    return ok({"total": len(followers), "followers": followers}, "Followers fetched")


@router.get("/following/{user_id}")
async def list_following(user_id: int):
    """Everyone this user follows."""
    following = await db.get_following(user_id)
    return ok({"total": len(following), "following": following}, "Following fetched")


@router.get("/follow/status/{user_id}")
async def follow_status(user_id: int, me: int = Depends(get_current_profile_id)):
    """Am I following this person? Drives the Follow / Unfollow button state."""
    following = await db.is_following(me=me, target=user_id)
    return ok({"following": following}, "Follow status fetched")


# ─── Message Requests ─────────────────────────────────────────────────────────

@router.post("/message-request/{user_id}", status_code=201)
async def send_request(user_id: int, me: int = Depends(get_current_profile_id)):
    """Send a message request. Returns 409 if one already exists."""
    result = await db.send_message_request(sender_id=me, receiver_id=user_id)
    return ok(result, "Message request sent")


@router.delete("/message-request/{user_id}")
async def withdraw_request(user_id: int, me: int = Depends(get_current_profile_id)):
    """Withdraw a pending message request. Returns 404 if no pending request exists."""
    result = await db.withdraw_message_request(sender_id=me, receiver_id=user_id)
    return ok(result, "Request withdrawn")


@router.patch("/message-request/{request_id}/accept")
async def accept_request(request_id: int, me: int = Depends(get_current_profile_id)):
    """Accept a message request. Only the receiver can accept."""
    result = await db.respond_to_request(request_id=request_id, me=me, action="accepted")
    return ok(result, "Request accepted")


@router.patch("/message-request/{request_id}/decline")
async def decline_request(request_id: int, me: int = Depends(get_current_profile_id)):
    """Decline a message request. Only the receiver can decline."""
    result = await db.respond_to_request(request_id=request_id, me=me, action="declined")
    return ok(result, "Request declined")


@router.get("/message-requests/received")
async def received_requests(me: int = Depends(get_current_profile_id)):
    """Pending message requests waiting on me to accept or decline."""
    requests = await db.get_received_requests(me=me)
    return ok({"total": len(requests), "requests": requests}, "Received requests fetched")


@router.get("/message-requests/sent")
async def sent_requests(me: int = Depends(get_current_profile_id)):
    """All message requests I have sent, with their current status."""
    requests = await db.get_sent_requests(me=me)
    return ok({"total": len(requests), "requests": requests}, "Sent requests fetched")


# ─── Search ───────────────────────────────────────────────────────────────────

@router.get("/search/suggestions")
async def suggestions(q: str = Query(..., min_length=2)):
    """Fuzzy suggestions using trigram similarity (pg_trgm)."""
    results = await db.search_suggestions(q=q)
    return ok({"total": len(results), "suggestions": results}, "Suggestions fetched")


@router.get("/search")
async def search(
    me:        int        = Depends(get_current_profile_id),
    q:         str | None = Query(default=None, description="Text search across city, state, commodity, role"),
    role:      str | None = Query(default=None),
    commodity: str | None = Query(default=None),
    city:      str | None = Query(default=None),
):
    """Filtered user search. All params except auth are optional. Returns up to 50 results."""
    results = await db.search_users(me=me, q=q, role=role, commodity=commodity, city=city)
    return ok({"total": len(results), "results": results}, "Search results fetched")
