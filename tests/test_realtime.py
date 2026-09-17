"""Socket.IO auth, presence and the membership rules behind the handlers.

There were no tests here at all, and the transport was just rewritten from
single-worker in-memory state to Redis-backed fan-out. The rules that matter are
not the transport: an unauthenticated socket must be refused, and a non-member
must not be able to join a group room, relay typing into a conversation, or mark
someone else's messages delivered.

Exercises the handlers and use cases directly with fakes — no server, no Redis.

    PYTHONPATH=. python tests/test_realtime.py
"""
from __future__ import annotations

import asyncio
import sys
from uuid import uuid4

from app.core import realtime
from app.core.security.jwt_handler import create_access_token
from app.modules.chat.application.use_cases.socket_events import (
    CanJoinGroupRoomUseCase,
    MarkDeliveredUseCase,
    RelayTypingUseCase,
)

fails: list[str] = []


def check(label, got, want):
    if got != want:
        fails.append(f"  {label}\n     got:  {got!r}\n     want: {want!r}")


class FakeRepo:
    """Membership answers, and a record of what was asked."""

    def __init__(self, *, group_member=False, dm_members=None, peer=None):
        self._group_member = group_member
        self._dm_members = dm_members or []
        self._peer = peer

    def is_group_member(self, group_id, user_id):
        return self._group_member

    def dm_member_ids(self, conv_id):
        return list(self._dm_members)

    def mark_delivered_and_get_peer(self, conv_id, user_id, now):
        return self._peer


# ── Membership rules ─────────────────────────────────────────────────────────

check("non-member cannot join a group room",
      CanJoinGroupRoomUseCase(FakeRepo(group_member=False)).execute(uuid4(), uuid4()), False)
check("member can join a group room",
      CanJoinGroupRoomUseCase(FakeRepo(group_member=True)).execute(uuid4(), uuid4()), True)

# Typing relay leaks "who is in this conversation" if it answers for a stranger.
check("non-member typing is relayed to nobody",
      RelayTypingUseCase(FakeRepo(dm_members=["u1", "u2"])).execute(uuid4(), "intruder"), [])
check("a member's typing goes to the peer only, never echoed back",
      RelayTypingUseCase(FakeRepo(dm_members=["u1", "u2"])).execute(uuid4(), "u1"), ["u2"])

check("non-member cannot mark messages delivered",
      MarkDeliveredUseCase(FakeRepo(peer=None)).execute(uuid4(), "intruder"), None)
peer_result = MarkDeliveredUseCase(FakeRepo(peer=("peer-id",))).execute(uuid4(), "u1")
check("a member gets the peer back to notify", peer_result[0], "peer-id")


# ── Connection auth and presence ─────────────────────────────────────────────

async def _connection_checks():
    joined: list[tuple] = []

    async def fake_enter_room(sid, room):
        joined.append((sid, room))

    real_enter, realtime.sio.enter_room = realtime.sio.enter_room, fake_enter_room
    try:
        check("a socket with no token is refused",
              await realtime.connect("sid-x", {}, {}), False)
        check("a socket with a junk token is refused",
              await realtime.connect("sid-x", {}, {"token": "not-a-jwt"}), False)
        check("a refused socket is not registered",
              realtime.user_for_sid("sid-x"), None)

        user_id = uuid4()
        token = create_access_token(user_id=user_id, session_id=uuid4(), profile_id=1)
        await realtime.connect("sid-ok", {}, {"token": token})
        check("a valid socket is mapped to its user",
              realtime.user_for_sid("sid-ok"), str(user_id))
        check("and is put in its own user room",
              ("sid-ok", f"user:{user_id}") in joined, True)

        await realtime.disconnect("sid-ok")
        check("disconnect forgets the socket", realtime.user_for_sid("sid-ok"), None)
    finally:
        realtime.sio.enter_room = real_enter


async def _listener_checks():
    # Idempotent start and a clean cancel: a leaked subscriber logged
    # "Task was destroyed but it is pending!" on every restart.
    await realtime.start_evict_listener()
    await realtime.start_evict_listener()
    await realtime.stop_evict_listener()
    await realtime.stop_evict_listener()        # must not raise
    check("listener stops cleanly and twice is fine", True, True)


asyncio.run(_connection_checks())
asyncio.run(_listener_checks())

if fails:
    print(f"FAIL ({len(fails)})\n" + "\n".join(fails))
    sys.exit(1)
print("PASS - realtime: unauthenticated sockets refused, non-members cannot join "
      "rooms, relay typing or mark delivered; presence and listener lifecycle clean")
