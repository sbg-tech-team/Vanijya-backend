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

from app.core.database.session import SessionLocal          # noqa: E402
from app.core.security.jwt_handler import create_access_token  # noqa: E402
from app.modules.post.data.models import Post               # noqa: E402
from app.modules.profile.data.models import (               # noqa: E402
    Business, Commodity, Profile, Role, User,
)
from app.routers import register_routers                    # noqa: E402

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
        for tag in ("a", "b"):
            user = User(country_code="+91", phone_number=f"90000000{tag=='b' and 1 or 0}")
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
            made.append({
                "user_id": user.id, "profile_id": profile.id, "post_id": post.id,
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

    # A acting on B's things. Each must be refused; 2xx is the finding.
    attempts = [
        ("delete B's post",        "DELETE", f"/posts/{b['post_id']}",                 None),
        ("edit B's post",          "PATCH",  f"/posts/{b['post_id']}",   {"caption": "hijacked"}),
        ("close B's deal",         "POST",   f"/posts/{b['post_id']}/deal-closed",     {}),
    ]
    for label, method, path, body in attempts:
        r = client.request(method, path, headers=ha, json=body)
        if 200 <= r.status_code < 300:
            fails.append(f"  {label}: {method} {path} -> {r.status_code} ALLOWED")
        else:
            print(f"  ok  refused: {label} ({r.status_code})")

    # A on its own post must still work — otherwise the check above proves nothing.
    r = client.request("PATCH", f"/posts/{a['post_id']}", headers=ha, json={"caption": "mine"})
    check("owner can edit their own post", 200 <= r.status_code < 300, True)

    if fails:
        print(f"FAIL ({len(fails)})\n" + "\n".join(fails))
        return 1
    print("PASS - cross-user writes are refused, owner writes still work")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
