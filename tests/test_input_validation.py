"""Malformed input must be rejected, never crash the endpoint.

A 4xx means the app looked at the input and said no. A 500 means the input got
past validation and blew up somewhere inside — that is an unhandled path, and
the ones that take user text are where injection and crash bugs live.

Every mutating endpoint is sent a spread of hostile bodies with a VALID token,
so this tests validation rather than auth. Anything that 500s is reported.

    DB_SSLMODE=disable SYNC_DATABASE_URL=postgresql+psycopg2://...localhost/... \
      python tests/test_input_validation.py
"""
from __future__ import annotations

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

from app.core.database.session import SessionLocal             # noqa: E402
from app.core.security.jwt_handler import create_access_token  # noqa: E402
from app.modules.profile.data.models import (                  # noqa: E402
    Business, Commodity, Profile, Role, User,
)
from app.routers import register_routers                       # noqa: E402

# Each is a shape that has broken a real API somewhere: wrong types, oversized
# text, nulls where objects go, and the classic injection payloads. None of them
# should reach a database driver or a formatter unchecked.
HOSTILE = [
    ("empty object", {}),
    ("nulls", {"content": None, "caption": None, "title": None, "name": None}),
    ("wrong types", {"content": 123, "caption": [], "title": {"a": 1},
                     "commodity_id": "abc", "category_id": "x", "is_public": "maybe"}),
    ("oversized text", {"content": "A" * 100_000, "caption": "B" * 100_000,
                        "title": "C" * 100_000, "name": "D" * 100_000}),
    ("sql injection", {"content": "'; DROP TABLE posts; --", "caption": "' OR '1'='1",
                       "title": "admin'--", "name": "1; DELETE FROM users"}),
    ("xss and control chars", {"content": "<script>alert(1)</script>",
                               "caption": "\\x00\\x01\\x02", "title": "../../etc/passwd"}),
    ("deep nesting", {"content": {"a": {"b": {"c": {"d": {"e": [1, 2, 3]}}}}}}),
    ("negative and huge numbers", {"commodity_id": -1, "category_id": 10**12,
                                   "quantity_min": -999, "page": -5, "limit": 10**9}),
]


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
        user = User(country_code="+91", phone_number=f"9{uuid4().int % 10**8:08d}")
        db.add(user); db.flush()
        prof = Profile(users_id=user.id, role_id=role.id, name="fuzz",
                       quantity_min=1, quantity_max=100, updated_at=now)
        db.add(prof); db.flush()
        db.add(Business(profile_id=prof.id, latitude=19.07, longitude=72.87))
        db.commit()
        return create_access_token(user_id=user.id, session_id=uuid4(), profile_id=prof.id)
    finally:
        db.close()


token = seed()
app = FastAPI()
register_routers(app)
# FUZZ_RAISE=1 surfaces the traceback of the first crash instead of a bare 500.
client = TestClient(app, raise_server_exceptions=bool(os.getenv("FUZZ_RAISE")))
headers = {"Authorization": f"Bearer {token}"}

SUBS = {"post_id": "1", "comment_id": "1", "profile_id": "1", "request_id": "1",
        "token": "x"}


def fill(path: str) -> str | None:
    out = path
    for k, v in SUBS.items():
        out = out.replace("{" + k + "}", v)
    while "{" in out:                      # any remaining uuid-ish param
        head, _, rest = out.partition("{")
        _, _, tail = rest.partition("}")
        out = head + str(uuid4()) + tail
    return out


spec = app.openapi()
crashes: list[str] = []
tried = 0

for path, ops in spec["paths"].items():
    for method in ops:
        m = method.upper()
        if m == "GET":
            continue
        url = fill(path)
        for label, payload in HOSTILE:
            tried += 1
            try:
                r = client.request(m, url, headers=headers, json=payload)
            except Exception as exc:
                crashes.append(f"{m} {path} [{label}] raised {type(exc).__name__}: {str(exc)[:70]}")
                continue
            if r.status_code >= 500:
                crashes.append(f"{m} {path} [{label}] -> {r.status_code}: {r.text[:120]}")

print(f"  sent {tried} malformed requests across {len(HOSTILE)} shapes")

if crashes:
    uniq = sorted(set(crashes))
    print(f"FAIL ({len(uniq)} endpoint/payload combinations returned 5xx)")
    for c in uniq[:40]:
        print("   ", c)
    sys.exit(1)
print("PASS - input validation: no malformed payload produced a 5xx")
