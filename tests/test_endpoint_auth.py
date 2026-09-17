"""Every endpoint must refuse an unauthenticated caller.

Walks the live route table rather than a hand-written list, so a new endpoint is
covered the day it is added — that is the failure mode this exists for. The four
job triggers shipped unauthenticated for exactly as long as nobody had a test
that would have noticed.

    DB_SSLMODE=disable SYNC_DATABASE_URL=... python tests/test_endpoint_auth.py

Needs a database only because importing the app builds an engine; no query runs.
"""
from __future__ import annotations

import sys
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import register_routers

# Deliberately public. Anything else answering 2xx without a token is a finding.
PUBLIC = {
    ("GET", "/"),
    ("GET", "/docs"), ("GET", "/redoc"), ("GET", "/openapi.json"),
    ("GET", "/docs/oauth2-redirect"),
    # Share links are opened from WhatsApp etc. by people with no account.
    # Rate-limited, because profile_id is sequential and these leak name,
    # company and city — see deeplink/presentation/router.py.
    ("GET", "/share/post/{post_id}"),
    ("GET", "/share/news/{article_id}"),
    ("GET", "/share/user/{profile_id}"),
    # The auth handshake itself.
    ("POST", "/auth/firebase-verify"),
    ("POST", "/auth/refresh"),
    ("GET", "/auth/dev-token"),        # 404s unless DEBUG=true; asserted below
}

# A 2xx means the endpoint ran. Everything else means it refused, and which
# refusal it picked (401 vs 422 vs 404) is not what this test is about.
def _fill(path: str) -> str:
    return path.replace("{post_id}", "1").replace("{profile_id}", "1") \
               .replace("{group_id}", str(uuid4())).replace("{article_id}", str(uuid4())) \
               .replace("{conv_id}", str(uuid4())).replace("{message_id}", str(uuid4())) \
               .replace("{user_id}", str(uuid4())).replace("{call_id}", str(uuid4())) \
               .replace("{comment_id}", "1").replace("{deal_id}", str(uuid4())) \
               .replace("{request_id}", "1").replace("{member_id}", str(uuid4())) \
               .replace("{token}", "x").replace("{media_id}", str(uuid4()))


def main() -> int:
    app = FastAPI()
    register_routers(app)
    app.get("/", status_code=200)(lambda: {"message": "Server is up and running!"})
    spec = app.openapi()
    client = TestClient(app, raise_server_exceptions=False)

    leaked, checked = [], 0
    for path, ops in spec["paths"].items():
        for method in ops:
            m = method.upper()
            if (m, path) in PUBLIC:
                continue
            checked += 1
            r = client.request(m, _fill(path), json={})
            if 200 <= r.status_code < 300:
                leaked.append(f"{m} {path} -> {r.status_code} WITHOUT A TOKEN")

    print(f"  checked {checked} endpoints, {len(PUBLIC)} deliberately public")

    # The dev-token backdoor mints a token for any profile by name. It must stay
    # shut unless DEBUG is explicitly on.
    import os
    if os.getenv("DEBUG", "").lower() != "true":
        r = client.get("/auth/dev-token", params={"name": "anyone"})
        if r.status_code != 404:
            leaked.append(f"GET /auth/dev-token -> {r.status_code}, expected 404 without DEBUG")

    if leaked:
        print(f"FAIL ({len(leaked)})")
        for x in leaked:
            print("   ", x)
        return 1
    print("PASS - no endpoint answers 2xx without a token; dev-token backdoor is shut")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
