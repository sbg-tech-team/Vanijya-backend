"""mark_seen.py — thin wrapper around rec_service.record_seen.

Exposed as a standalone use case so routers and other modules can call
mark_seen(repo, profile_id, post_ids) without importing from rec_service directly.
"""

from sqlalchemy.orm import Session

from app.modules.post.recommendation import service as rec_service
from app.modules.post.domain.interfaces.repository import IPostRepository


def mark_seen(repo: IPostRepository, profile_id: int, post_ids: list[int]) -> None:
    """Record that profile_id has seen the given post IDs.

    Delegates to the recommendation layer; silently ignores failures so
    that a recommendation-index outage never blocks the caller.
    """
    if not post_ids:
        return
    try:
        rec_service.record_seen(repo.session, profile_id, post_ids)
    except Exception:
        pass
