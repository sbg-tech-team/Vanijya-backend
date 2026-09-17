"""Query counts per request, held to a budget.

Against production the database is a round trip away — measured at 129 ms — so
what costs a request is not how much work it does but how many times it goes
back. The feed made 24 queries: about 3.1 s on the wire before any work.

This pins the counts. Going over means somebody reintroduced a round trip, and
on a co-located database it will be invisible in testing.

    DB_SSLMODE=disable SYNC_DATABASE_URL=postgresql+psycopg2://...localhost/... \
      python tests/test_query_budget.py
"""
from __future__ import annotations

import collections
import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

DB = os.environ.get("SYNC_DATABASE_URL", "")
if "localhost" not in DB and "127.0.0.1" not in DB:
    sys.exit("refusing to run: SYNC_DATABASE_URL is not a local database")

import main  # noqa: F401,E402

from fastapi import FastAPI                                    # noqa: E402
from fastapi.testclient import TestClient                      # noqa: E402
from sqlalchemy import event                                   # noqa: E402

from app.core.database.session import SessionLocal, engine     # noqa: E402
from app.core.security.jwt_handler import create_access_token  # noqa: E402
from app.modules.post.data.models import Post                  # noqa: E402
from app.modules.profile.data.models import (                  # noqa: E402
    Business, Commodity, Profile, Role, User,
)
from app.routers import register_routers                       # noqa: E402

# Ceilings, not targets. Raise one only with a reason — each unit is a round trip.
BUDGET = {
    "/posts/mine": 8,
    "/posts/recommendation/feed?limit=10": 22,
}

counter = collections.Counter()


@event.listens_for(engine, "after_cursor_execute")
def _count(conn, cursor, statement, params, context, executemany):
    counter["n"] += 1


def seed():
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    try:
        role = db.query(Role).first() or Role(name="trader")
        if role.id is None:
            db.add(role); db.flush()
        com = db.query(Commodity).first() or Commodity(name="cotton")
        if com.id is None:
            db.add(com); db.flush()
        u = User(country_code="+91", phone_number=f"9{uuid4().int % 10**8:08d}")
        db.add(u); db.flush()
        p = Profile(users_id=u.id, role_id=role.id, name="budget",
                    quantity_min=1, quantity_max=100, updated_at=now)
        db.add(p); db.flush()
        db.add(Business(profile_id=p.id, latitude=19.07, longitude=72.87))
        for i in range(5):
            db.add(Post(profile_id=p.id, category_id=1, commodity_id=com.id,
                        title=f"budget {i}", caption="x", is_public=True))
        db.commit()
        return create_access_token(user_id=u.id, session_id=uuid4(), profile_id=p.id)
    finally:
        db.close()


token = seed()
app = FastAPI()
register_routers(app)
client = TestClient(app, raise_server_exceptions=False)
headers = {"Authorization": f"Bearer {token}"}

fails = []
for path, budget in BUDGET.items():
    counter.clear()
    r = client.get(path, headers=headers)
    n = counter["n"]
    status = "ok " if n <= budget and r.status_code == 200 else "OVER"
    print(f"  {status} {path:42} {n:3} queries (budget {budget})")
    if r.status_code != 200:
        fails.append(f"  {path} returned {r.status_code}")
    elif n > budget:
        fails.append(f"  {path}: {n} queries, budget {budget} "
                     f"— that is {(n - budget) * 129 / 1000:.1f}s extra against production")

if fails:
    print(f"FAIL ({len(fails)})\n" + "\n".join(fails))
    sys.exit(1)
print("PASS - query budget: every endpoint within its round-trip budget")
