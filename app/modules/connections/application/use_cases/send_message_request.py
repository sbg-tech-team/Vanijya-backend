"""
Message request use cases — Section B of the original service.py.

Handles sending, withdrawing, and listing message requests.
No FastAPI imports. Domain exceptions are raised instead of HTTPException.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import redis as redis_lib

from app.modules.connections.application.formatters import fmt_profile
from app.modules.connections.domain.interfaces.repository import IConnectionsRepository
from app.modules.connections.domain.exceptions import (
    AlreadyConnectedError,
    MessageRequestAlreadySentError,
    NoPendingRequestError,
    ProfileNotFoundError,
    SelfRequestError,
)
from app.recommendation.session_taste import ActionType
from app.recommendation.amplify import write_commodity_signals

_MODULE = "connections"



# ---------------------------------------------------------------------------
# B. Message requests
# ---------------------------------------------------------------------------


def send_message_request(
    repo: IConnectionsRepository,
    sender_id: UUID,
    receiver_id: UUID,
    first_message: str | None = None,
    *,
    rc: "redis_lib.Redis | None" = None,
    actor_profile_id: int | None = None,
    commodity_ids: list[int] | None = None,
    role_id: int | None = None,
) -> dict:
    def _record() -> None:
        if actor_profile_id is not None:
            write_commodity_signals(rc, actor_profile_id, _MODULE,
                commodity_ids or [], ActionType.CONNECTION_MSG, role_id)

    if sender_id == receiver_id:
        raise SelfRequestError()
    # Same foreign key trap as follow_user: a made-up receiver id reached the
    # insert and came back as a 500.
    if not repo.load_profile(receiver_id):
        raise ProfileNotFoundError(receiver_id)
    existing = repo.get_message_request(sender_id, receiver_id)
    if existing:
        if existing.status == "declined":
            existing = repo.revive_declined_request(existing, first_message)
            _record()
            return {"id": existing.id, "status": existing.status, "sent_at": existing.sent_at}
        if existing.status == "accepted":
            raise AlreadyConnectedError(receiver_id)
        raise MessageRequestAlreadySentError(receiver_id)
    req = repo.add_message_request(sender_id, receiver_id, first_message)
    _record()
    return {"id": req.id, "status": req.status, "sent_at": req.sent_at}


def withdraw_message_request(
    repo: IConnectionsRepository, sender_id: UUID, receiver_id: UUID
) -> dict:
    if not repo.delete_withdrawable_request(sender_id, receiver_id):
        raise NoPendingRequestError(receiver_id)
    return {"status": "withdrawn", "receiver_id": str(receiver_id)}


def get_received_requests(repo: IConnectionsRepository, me: UUID) -> list[dict]:
    """Pending inbox — requests waiting on me to accept or decline."""
    reqs = repo.list_received_requests(me)
    profiles = repo.load_profiles_bulk([r.sender_id for r in reqs])
    return [
        {
            "request_id": r.id,
            "from": fmt_profile(profiles[r.sender_id]),
            "first_message": r.first_message,
            "sent_at": r.sent_at,
        }
        for r in reqs
        if r.sender_id in profiles
    ]


def get_sent_requests(repo: IConnectionsRepository, me: UUID) -> list[dict]:
    """All requests I have sent, all statuses."""
    reqs = repo.list_sent_requests(me)
    profiles = repo.load_profiles_bulk([r.receiver_id for r in reqs])
    return [
        {
            "request_id":    r.id,
            "to":            fmt_profile(profiles[r.receiver_id]),
            "status":        r.status,
            "first_message": r.first_message,
            "sent_at":       r.sent_at,
            "acted_at":      r.acted_at,
        }
        for r in reqs
        if r.receiver_id in profiles
    ]
