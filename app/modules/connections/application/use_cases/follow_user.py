"""
Follow graph use cases — Section A of the original service.py.

Handles follow/unfollow edges and follower/following list retrieval.
No FastAPI imports, no SQL: all persistence goes through IConnectionsRepository.
Domain exceptions are raised instead of HTTPException.
"""
from __future__ import annotations

from typing import Protocol
from uuid import UUID

import redis as redis_lib

from app.modules.connections.application.formatters import fmt_profile
from app.modules.connections.domain.exceptions import (
    AlreadyFollowingError,
    NotFollowingError,
    ProfileNotFoundError,
    SelfFollowError,
)
from app.modules.connections.domain.interfaces.repository import IConnectionsRepository
from app.recommendation.amplify import write_commodity_signals
from app.recommendation.session_taste import ActionType

_MODULE = "connections"


class TaskQueue(Protocol):
    """Shaped like fastapi.BackgroundTasks' add_task — the application layer
    stays framework-free, so it depends on this shape, not on FastAPI; the
    presentation layer passes the real BackgroundTasks object in. Shared by
    follow_user.py and send_message_request.py, both in this module."""
    def add_task(self, func, *args, **kwargs) -> None: ...


# ---------------------------------------------------------------------------
# A. Follow graph
# ---------------------------------------------------------------------------

def follow_user(
    repo: IConnectionsRepository,
    follower_id: UUID,
    following_id: UUID,
    *,
    rc: "redis_lib.Redis | None" = None,
    actor_profile_id: int | None = None,
    commodity_ids: list[int] | None = None,
    role_id: int | None = None,
    background_tasks: TaskQueue | None = None,
) -> dict:
    if follower_id == following_id:
        raise SelfFollowError()
    # Without this the insert hits a foreign key violation and surfaces as a 500.
    # Any client can trigger it with a made-up id.
    if not repo.load_profile(following_id):
        raise ProfileNotFoundError(following_id)
    if repo.get_follow(follower_id, following_id):
        raise AlreadyFollowingError(following_id)
    repo.add_follow(follower_id, following_id)
    if actor_profile_id is not None:
        def _signal():
            write_commodity_signals(rc, actor_profile_id, _MODULE,
                commodity_ids or [], ActionType.CONNECTION_FOLLOW, role_id)
        if background_tasks is not None:
            background_tasks.add_task(_signal)
        else:
            _signal()
    return {"status": "following", "following_id": str(following_id)}


def record_profile_view(
    rc: redis_lib.Redis,
    viewer_profile_id: int,
    commodity_ids: list[int],
    role_id: int | None = None,
    background_tasks: TaskQueue | None = None,
) -> None:
    """Redis-only taste signal — the viewer opened a profile card. No DB
    write. Best-effort, so it's deferred when background_tasks is given."""
    def _run():
        write_commodity_signals(rc, viewer_profile_id, _MODULE,
            commodity_ids, ActionType.CONNECTION_VIEW, role_id)
    if background_tasks is not None:
        background_tasks.add_task(_run)
    else:
        _run()


def unfollow_user(repo: IConnectionsRepository, follower_id: UUID, following_id: UUID) -> dict:
    """
    One-directional unfollow:
      - removes the caller's follow edge (follower -> following) and adjusts counts
      - deletes the caller's own outgoing message request to that user, if any
    The other person's follow-back, their request to the caller, and any shared
    DM conversation are left untouched.
    """
    if not repo.remove_follow(follower_id, following_id):
        raise NotFollowingError(following_id)
    return {"status": "unfollowed", "following_id": str(following_id)}


def get_followers(repo: IConnectionsRepository, user_id: UUID) -> list[dict]:
    conns = repo.list_followers(user_id)
    profiles = repo.load_profiles_bulk([c.follower_id for c in conns])
    result = []
    for conn in conns:
        p = profiles.get(conn.follower_id)
        if p:
            result.append({**fmt_profile(p), "followed_at": conn.followed_at})
    return result


def get_following(repo: IConnectionsRepository, user_id: UUID) -> list[dict]:
    conns = repo.list_following(user_id)
    profiles = repo.load_profiles_bulk([c.following_id for c in conns])
    result = []
    for conn in conns:
        p = profiles.get(conn.following_id)
        if p:
            result.append({**fmt_profile(p), "followed_at": conn.followed_at})
    return result


def is_following(repo: IConnectionsRepository, me: UUID, target: UUID) -> bool:
    return repo.get_follow(me, target) is not None
