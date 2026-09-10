"""Block / unblock use cases.

Return shapes are byte-identical to app_old/modules/safety/service.py — the
live frontend depends on these exact keys.
"""
from __future__ import annotations

from uuid import UUID

from app.modules.safety.domain.exceptions import (
    AlreadyBlockedError,
    BlockNotFoundError,
    BlockSelfError,
)
from app.modules.safety.domain.interfaces.repository import ISafetyRepository


def block_user(repo: ISafetyRepository, blocker_id: UUID, blocked_id: UUID) -> dict:
    if blocker_id == blocked_id:
        raise BlockSelfError("Cannot block yourself.")
    if repo.block_exists(blocker_id, blocked_id):
        raise AlreadyBlockedError("User is already blocked.")
    repo.add_block(blocker_id, blocked_id)
    return {"status": "blocked", "blocked_id": str(blocked_id)}


def unblock_user(repo: ISafetyRepository, blocker_id: UUID, blocked_id: UUID) -> dict:
    if not repo.remove_block(blocker_id, blocked_id):
        raise BlockNotFoundError("Block not found.")
    return {"status": "unblocked", "blocked_id": str(blocked_id)}


def list_blocked(
    repo: ISafetyRepository, blocker_id: UUID, page: int = 1, limit: int = 20
) -> dict:
    rows, total = repo.list_blocked(blocker_id, page=page, limit=limit)
    return {
        "blocked": [
            {
                "blocked_id": str(b.blocked_id),
                "blocked_at": b.blocked_at,
                "name": b.name,
                "avatar_url": b.avatar_url,
            }
            for b in rows
        ],
        "total": total,
        "page": page,
        "limit": limit,
    }


def block_status(repo: ISafetyRepository, blocker_id: UUID, blocked_id: UUID) -> dict:
    return {
        "blocker_id": str(blocker_id),
        "blocked_id": str(blocked_id),
        "is_blocked": repo.block_exists(blocker_id, blocked_id),
    }


def is_blocked(repo: ISafetyRepository, blocker_id: UUID, blocked_id: UUID) -> bool:
    """True if blocker_id has blocked blocked_id. Used by other modules."""
    return repo.block_exists(blocker_id, blocked_id)


def either_blocked(repo: ISafetyRepository, user_a: UUID, user_b: UUID) -> bool:
    """True if either user has blocked the other. Useful for DM / feed guards."""
    return repo.either_blocked(user_a, user_b)
