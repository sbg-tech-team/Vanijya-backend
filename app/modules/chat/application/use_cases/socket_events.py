"""Use cases behind the chat Socket.IO handlers.

The socket handlers are controllers like any HTTP route: they own transport,
not rules. The membership checks that decide whether a typing indicator may be
relayed or a room may be joined live here, against the repository interface.
"""
from datetime import datetime, timezone
from uuid import UUID


class CanJoinGroupRoomUseCase:
    def __init__(self, repo):
        self.repo = repo

    def execute(self, group_id: UUID, user_id: UUID) -> bool:
        return bool(self.repo.is_group_member(group_id, user_id))


class RelayTypingUseCase:
    """Who should receive a DM typing indicator — empty if the sender is not a member."""

    def __init__(self, repo):
        self.repo = repo

    def execute(self, conv_id: UUID, user_id: str) -> list[str]:
        member_ids = self.repo.dm_member_ids(conv_id)
        if user_id not in member_ids:
            return []
        return [mid for mid in member_ids if mid != user_id]


class MarkDeliveredUseCase:
    """Bump this member's delivery high-water mark. Returns (peer_id, timestamp)
    or None when the user is not a member of the conversation."""

    def __init__(self, repo):
        self.repo = repo

    def execute(self, conv_id: UUID, user_id: str):
        now = datetime.now(timezone.utc)
        peer = self.repo.mark_delivered_and_get_peer(conv_id, user_id, now)
        if not peer:
            return None
        return peer[0], now
