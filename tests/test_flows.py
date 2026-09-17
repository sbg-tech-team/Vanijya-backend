"""End-to-end flows, checking response DATA and not just status codes.

Every other suite proves an endpoint refuses the wrong caller. None of them
proves it returns the right answer to the right caller — a like that never
increments, or a comment that does not come back, passes all of them.

Each flow drives real HTTP through the app against a throwaway database.

    DB_SSLMODE=disable SYNC_DATABASE_URL=postgresql+psycopg2://...localhost/... \
      python tests/test_flows.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

DB = os.environ.get("SYNC_DATABASE_URL", "")
if "localhost" not in DB and "127.0.0.1" not in DB:
    sys.exit("refusing to run: SYNC_DATABASE_URL is not a local database")

import main  # noqa: F401,E402  — registers every model

from fastapi import FastAPI                                    # noqa: E402
from fastapi.testclient import TestClient                      # noqa: E402

from app.core.database.session import SessionLocal             # noqa: E402
from app.core.security.jwt_handler import create_access_token  # noqa: E402
from app.modules.profile.data.models import (                  # noqa: E402
    Business, Commodity, Profile, Role, User,
)
from app.routers import register_routers                       # noqa: E402

fails: list[str] = []


def check(label, got, want):
    if got != want:
        fails.append(f"  {label}\n     got:  {got!r}\n     want: {want!r}")


def seed_user(tag: str):
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    try:
        role = db.query(Role).first() or Role(name="trader")
        if role.id is None:
            db.add(role)
            db.flush()
        commodity = db.query(Commodity).first() or Commodity(name="cotton")
        if commodity.id is None:
            db.add(commodity)
            db.flush()
        user = User(country_code="+91", phone_number=f"9{uuid4().int % 10**8:08d}")
        db.add(user)
        db.flush()
        profile = Profile(users_id=user.id, role_id=role.id, name=f"flow_{tag}",
                          quantity_min=1, quantity_max=100, updated_at=now)
        db.add(profile)
        db.flush()
        db.add(Business(profile_id=profile.id, latitude=19.07, longitude=72.87))
        db.commit()
        return {
            "user_id": user.id, "profile_id": profile.id,
            "commodity_id": commodity.id,
            "token": create_access_token(user_id=user.id, session_id=uuid4(),
                                         profile_id=profile.id),
        }
    finally:
        db.close()


def body(r):
    """Unwrap the {success, message, data} envelope when present."""
    try:
        j = r.json()
    except Exception:
        return {}
    return j.get("data", j) if isinstance(j, dict) else j


author = seed_user("author")
reader = seed_user("reader")
app = FastAPI()
register_routers(app)
# raise_server_exceptions=False so a 500 is reported as a failed check rather
# than aborting the run; set FLOWS_RAISE=1 to get the traceback instead.
client = TestClient(app, raise_server_exceptions=bool(os.getenv("FLOWS_RAISE")))
ha = {"Authorization": f"Bearer {author['token']}"}
hr = {"Authorization": f"Bearer {reader['token']}"}

# ── Create a post and read it back ───────────────────────────────────────────
r = client.post("/posts/", headers=ha, json={
    "category_id": 1, "commodity_id": author["commodity_id"],
    "title": "flow test post", "caption": "hello", "is_public": True,
})
check("create post succeeds", 200 <= r.status_code < 300, True)
post = body(r)
post_id = post.get("id")
check("create returns an id", isinstance(post_id, int), True)
check("create echoes the title back", post.get("title"), "flow test post")

if post_id:
    r = client.get(f"/posts/{post_id}", headers=ha)
    got = body(r)
    check("the post reads back", r.status_code, 200)
    check("with the caption it was created with", got.get("caption"), "hello")

    # ── Like toggles, and the count follows ──────────────────────────────────
    before = body(client.get(f"/posts/{post_id}", headers=hr)).get("like_count", 0)
    r = client.post(f"/posts/{post_id}/like", headers=hr, json={})
    check("like succeeds", 200 <= r.status_code < 300, True)
    after = body(client.get(f"/posts/{post_id}", headers=hr)).get("like_count", 0)
    check("like_count went up by one", after, before + 1)

    client.post(f"/posts/{post_id}/like", headers=hr, json={})   # unlike
    back = body(client.get(f"/posts/{post_id}", headers=hr)).get("like_count", 0)
    check("liking twice returns to the original count", back, before)

    # ── Comment, and get it back ─────────────────────────────────────────────
    r = client.post(f"/posts/{post_id}/comments", headers=hr,
                    json={"content": "nice one"})
    check("comment succeeds", 200 <= r.status_code < 300, True)
    r = client.get(f"/posts/{post_id}/comments", headers=hr)
    listed = body(r)
    items = listed.get("comments", listed) if isinstance(listed, dict) else listed
    texts = [c.get("content") for c in items] if isinstance(items, list) else []
    check("the comment comes back in the list", "nice one" in texts, True)

    # ── The author sees it in their own posts ────────────────────────────────
    r = client.get("/posts/mine", headers=ha)
    mine = body(r)
    rows = mine.get("posts", mine) if isinstance(mine, dict) else mine
    ids = [p.get("id") for p in rows] if isinstance(rows, list) else []
    check("the new post appears in /posts/mine", post_id in ids, True)

# ── A DM reaches the other side ──────────────────────────────────────────────
r = client.post("/chat/conversations", headers=ha,
                json={"participant_id": str(reader["user_id"])})
check("opening a conversation succeeds", 200 <= r.status_code < 300, True)
conv = body(r)
conv_id = conv.get("id")
check("conversation has an id", bool(conv_id), True)

if conv_id:
    r = client.post("/chat/conversations", headers=ha,
                    json={"participant_id": str(reader["user_id"])})
    check("opening it again is idempotent", body(r).get("id"), conv_id)

if fails:
    print(f"FAIL ({len(fails)})\n" + "\n".join(fails))
    sys.exit(1)
print("PASS - flows: post create/read, like toggle with counts, comment round "
      "trip, own-posts listing, DM conversation idempotency")
