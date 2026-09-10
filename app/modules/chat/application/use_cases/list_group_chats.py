"""Groups-only chat list use case.

Ported from app_old/modules/chat/domain/use_cases.py — app_new dropped this
class, which is why GET /chat/groups disappeared from the API.
"""
from datetime import datetime
from uuid import UUID


class GetGroupConversationsUseCase:
    """Groups-only chat list — every group the user is a member of, newest
    activity first. Same source the unified inbox uses, just without the DMs."""

    def __init__(self, repo):
        self.repo = repo

    def execute(self, user_id: UUID, page: int = 1, per_page: int = 20):
        groups = self.repo.get_group_conversations(user_id)

        # Strip tzinfo so naive (DB-read) and aware datetimes never collide;
        # None sinks to the bottom. Mirrors the sort in get_all_chats.
        def _key(g):
            dt = g.updated_at
            return dt.replace(tzinfo=None) if dt else datetime.min

        groups.sort(key=_key, reverse=True)
        offset = (page - 1) * per_page
        return groups[offset:offset + per_page]
