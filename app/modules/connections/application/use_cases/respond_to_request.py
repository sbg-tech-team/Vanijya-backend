"""
Respond-to-request use case — part of Section B of the original service.py.

Handles accepting or declining an incoming message request, including
DM conversation creation/reactivation and seeding the opening message.
No FastAPI imports. Domain exceptions are raised instead of HTTPException.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID


from app.modules.connections.domain.interfaces.repository import IConnectionsRepository
from app.modules.connections.domain.exceptions import (
    ConversationBlockedError,
    MessageRequestNotFoundError,
)


# ---------------------------------------------------------------------------
# B (continued). Respond to message request
# ---------------------------------------------------------------------------


def respond_to_request(
    repo: IConnectionsRepository, request_id: int, me: UUID, action: str
) -> dict:
    """action must be 'accepted' or 'declined'. Only the receiver can call this.

    On 'accepted', the DM conversation between the two users is created (or, if one
    already exists, reactivated) with status 'active' — the message request is the
    consent, so both sides can chat immediately afterwards.
    """
    req = repo.get_pending_request_for_receiver(request_id, me)
    if not req:
        raise MessageRequestNotFoundError(request_id)

    repo.set_message_request_status(req, action)

    conv_id = None
    if action == "accepted":
        conv_id = _activate_dm(repo, initiator_id=req.sender_id, other_id=req.receiver_id)
        # Seed the request's opening line as the first message of the conversation,
        # in the same transaction so the DM is never observed empty after accept.
        if req.first_message:
            repo.seed_first_message(conv_id, sender_id=req.sender_id, body=req.first_message)

    repo.commit()
    result = {"id": request_id, "status": action, "sender_id": str(req.sender_id)}
    if conv_id is not None:
        result["conversation_id"] = str(conv_id)
    return result


def _activate_dm(repo: IConnectionsRepository, initiator_id: UUID, other_id: UUID) -> UUID:
    """Create or reactivate the DM conversation between two users and return its id.
    The request sender is recorded as the conversation initiator. Does not commit —
    the caller owns the transaction."""
    from app.modules.chat.domain.value_objects import ConversationStatus

    conv = repo.find_dm_between(initiator_id, other_id)
    if conv is None:
        return repo.create_dm(initiator_id, other_id, datetime.now(timezone.utc))
    # Never revive a blocked conversation — an explicit block must not be
    # silently undone by accepting a message request.
    if conv.status == ConversationStatus.BLOCKED:
        raise ConversationBlockedError()
    repo.activate_dm(conv)
    return conv.id
