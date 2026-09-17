"""Can user A touch user B's data?

The unauthenticated sweep (test_endpoint_auth.py) proves an endpoint asks for a
token. It does not prove the endpoint checks WHOSE token it is — an endpoint
that happily deletes any post for any signed-in caller passes that sweep. This
one seeds two real users and has each try to act on the other's resources.

    DB_SSLMODE=disable SYNC_DATABASE_URL=postgresql+psycopg2://... \
      python tests/test_authorization.py

Destructive: it writes and deletes rows, so point it at a throwaway database.
It refuses to run against anything that looks like production.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

DB = os.environ.get("SYNC_DATABASE_URL", "")
if "localhost" not in DB and "127.0.0.1" not in DB:
    sys.exit("refusing to run: SYNC_DATABASE_URL is not a local database")

import main  # noqa: F401,E402  — registers every model, so FKs across modules resolve

from app.core.database.session import SessionLocal          # noqa: E402
from app.core.security.jwt_handler import create_access_token  # noqa: E402
from app.modules.chat.data.models import (                  # noqa: E402
    Conversation, ConversationMember, Message,
)
from app.modules.groups.data.models import Group, GroupMember  # noqa: E402
from app.modules.post.data.models import Post               # noqa: E402
from app.modules.profile.data.models import (               # noqa: E402
    Business, Commodity, Profile, Role, User,
)
from app.routers import register_routers                    # noqa: E402

# Endpoints where acting on someone else's id is the whole point: following a
# user, reporting them, asking to join their group. Each is a deliberate entry,
# not a blanket skip.
EXPECTED_OPEN: set[tuple[str, str]] = {
    # Engaging with someone else's post is the product.
    ("POST", "/posts/{post_id}/like"),
    ("POST", "/posts/{post_id}/save"),
    ("POST", "/posts/{post_id}/record-share"),
    # The social graph is built by acting on other people.
    ("POST", "/connections/follow/{target_id}"),
    ("DELETE", "/connections/follow/{target_id}"),
    ("POST", "/connections/message-request/{target_id}"),
    ("DELETE", "/connections/message-request/{target_id}"),
    # Joining and leaving a group you do not own.
    ("POST", "/api/v1/groups/{group_id}/join"),
    ("DELETE", "/api/v1/groups/{group_id}/leave"),
    # Blocking is by definition aimed at another account.
    ("POST", "/safety/block/{target_id}"),
    ("DELETE", "/safety/block/{target_id}"),
}

fails: list[str] = []


def check(label: str, got, want) -> None:
    if got != want:
        fails.append(f"  {label}\n     got:  {got!r}\n     want: {want!r}")


def seed():
    """Two users, each owning one post. Returns (a, b) context dicts."""
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    try:
        role = db.query(Role).first()
        if role is None:
            role = Role(name="trader")
            db.add(role)
            db.flush()
        commodity = db.query(Commodity).first()
        if commodity is None:
            commodity = Commodity(name="cotton")
            db.add(commodity)
            db.flush()

        made = []
        # Unique per run: the phone number is uniquely constrained, and a test
        # that only passes on a virgin database is a test nobody runs twice.
        stamp = uuid4().int % 10**7
        for i, tag in enumerate(("a", "b")):
            user = User(country_code="+91", phone_number=f"9{stamp:07d}{i}")
            db.add(user)
            db.flush()
            profile = Profile(
                users_id=user.id, role_id=role.id, name=f"user_{tag}",
                quantity_min=1, quantity_max=100, updated_at=now,
            )
            db.add(profile)
            db.flush()
            db.add(Business(profile_id=profile.id, latitude=19.07, longitude=72.87))
            post = Post(
                profile_id=profile.id, category_id=1, commodity_id=commodity.id,
                title=f"post of {tag}", caption="x", is_public=True,
            )
            db.add(post)
            db.flush()
            group = Group(id=uuid4(), name=f"group of {tag}",
                          created_by=user.id, created_at=now)
            db.add(group)
            db.flush()
            db.add(GroupMember(group_id=group.id, user_id=user.id, joined_at=now))

            conv = Conversation(updated_at=now)
            db.add(conv)
            db.flush()
            db.add(ConversationMember(conversation_id=conv.id, user_id=user.id))
            msg = Message(context_type="dm", context_id=conv.id, sender_id=user.id)
            db.add(msg)
            db.flush()

            made.append({
                "user_id": user.id, "profile_id": profile.id, "post_id": post.id,
                "group_id": group.id, "conv_id": conv.id, "message_id": msg.id,
                "token": create_access_token(
                    user_id=user.id, session_id=uuid4(), profile_id=profile.id),
            })
        db.commit()
        return made[0], made[1]
    finally:
        db.close()


def main() -> int:
    a, b = seed()
    app = FastAPI()
    register_routers(app)
    client = TestClient(app, raise_server_exceptions=False)
    ha = {"Authorization": f"Bearer {a['token']}"}

    # Every mutating endpoint that names a resource, called by A with B's ids.
    # Generated from the live route table rather than listed by hand, so a new
    # endpoint is covered the day it ships.
    spec = app.openapi()
    subs = {
        "post_id": str(b["post_id"]), "group_id": str(b["group_id"]),
        "conv_id": str(b["conv_id"]), "message_id": str(b["message_id"]),
        "user_id": str(b["user_id"]), "profile_id": str(b["profile_id"]),
        "target_id": str(b["user_id"]), "target_user_id": str(b["user_id"]),
        "deal_id": str(uuid4()), "call_id": str(uuid4()),
        "article_id": str(uuid4()), "comment_id": "1", "request_id": "1",
        "member_id": str(b["user_id"]), "media_id": str(uuid4()), "token": "x",
    }

    def fill(path: str) -> str | None:
        out = path
        for key, val in subs.items():
            out = out.replace("{" + key + "}", val)
        return None if "{" in out else out

    allowed = 0
    for path, ops in spec["paths"].items():
        for method in ops:
            m = method.upper()
            if m == "GET" or "{" not in path:
                continue
            url = fill(path)
            if url is None:
                continue                      # unknown param — cannot address B's row
            allowed += 1
            r = client.request(m, url, headers=ha, json={})
            if 200 <= r.status_code < 300 and (m, path) not in EXPECTED_OPEN:
                fails.append(
                    f"  {m} {path} -> {r.status_code}: user A acted on user B's resource")

    print(f"  tried {allowed} mutating endpoints as another user")

    # A on its own post must still work — otherwise the checks above prove nothing.
    r = client.request("PATCH", f"/posts/{a['post_id']}", headers=ha, json={"caption": "mine"})
    check("owner can still edit their own post", 200 <= r.status_code < 300, True)

    if fails:
        print(f"FAIL ({len(fails)})\n" + "\n".join(fails))
        return 1
    print("PASS - cross-user writes are refused, owner writes still work")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
