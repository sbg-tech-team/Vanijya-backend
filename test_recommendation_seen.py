"""
Connections Recommendation — Full API + Redis Test
----------------------------------------------------
Run from the backend folder:
    python scripts/test_recommendation_seen.py

Creates real users + profiles + embeddings directly in the DB,
mints access tokens — no Firebase, no OTP, no live server needed.
Uses FastAPI TestClient (in-process) and connects to the real Redis
instance from REDIS_URL in .env.

Coverage:
  A. GET /recommendations/ — basic structure + pagination
  B. Exclusion: already-following users filtered out
  C. Exclusion: already-requested users filtered out
  D. POST /recommendations/seen — stores seen set in Redis
  E. GET /recommendations/ — seen users excluded after marking
  F. POST /recommendations/seen — TTL is set once, not reset on re-call
  G. POST /recommendations/seen — validation (max 50 IDs, 401 without token)
  H. Redis key inspection — key format and TTL value
  I. POST /recommendations/search — public custom search (no auth)
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi.testclient import TestClient
from sqlalchemy import text

from main import app
from app.core.database.session import SessionLocal
from app.core.redis_client import get_redis
from app.core.security.jwt_handler import create_access_token
from app.modules.connections.encoding.vector import build_candidate_vector
from app.modules.profile.models import Business, Profile, Profile_Commodity, User

client = TestClient(app, raise_server_exceptions=True)

# ---------------------------------------------------------------------------
# Test identifiers — chosen to avoid collision with real users
# ---------------------------------------------------------------------------
COUNTRY = "+91"
USER_A_PHONE = "9000000081"   # trader  (the searcher)
USER_B_PHONE = "9000000082"   # exporter (should appear in A's recs)
USER_C_PHONE = "9000000083"   # broker   (used for exclusion tests)

_SEEN_TTL_SECONDS = 172_800   # 48 h — must match service.py _SEEN_TTL

# ---------------------------------------------------------------------------
# Console helpers
# ---------------------------------------------------------------------------
PASS_COUNT = 0
FAIL_COUNT = 0


def section(title: str) -> None:
    print(f"\n{'#' * 64}\n  {title}\n{'#' * 64}")


def show(label: str, payload) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {label}")
    print(f"{'─' * 60}")
    print(json.dumps(payload, indent=2, default=str))


def check(name: str, condition: bool, actual=None) -> None:
    global PASS_COUNT, FAIL_COUNT
    if condition:
        print(f"  [PASS] {name}")
        PASS_COUNT += 1
    else:
        print(f"  [FAIL] {name}  |  got: {actual}")
        FAIL_COUNT += 1


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _create_user_and_profile(
    phone: str,
    name: str,
    role_id: int,
    commodity_ids: list[int],
    lat: float,
    lon: float,
    city: str,
    state_name: str,
    qty_min: int = 100,
    qty_max: int = 500,
) -> tuple[uuid.UUID, int]:
    """Insert user + profile + business + commodities. Returns (user_id, profile_id)."""
    db = SessionLocal()
    try:
        user = User(country_code=COUNTRY, phone_number=phone)
        db.add(user)
        db.flush()

        profile = Profile(
            users_id=user.id,
            role_id=role_id,
            name=name,
            quantity_min=qty_min,
            quantity_max=qty_max,
            is_user_verified=False,
            is_business_verified=False,
        )
        db.add(profile)
        db.flush()

        db.add(Business(
            profile_id=profile.id,
            business_name=f"{name} Pvt Ltd",
            city=city,
            state=state_name,
            latitude=lat,
            longitude=lon,
        ))
        for cid in commodity_ids:
            db.add(Profile_Commodity(profile_id=profile.id, commodity_id=cid))

        db.commit()
        return user.id, profile.id
    finally:
        db.close()


def _insert_embedding(
    user_id: uuid.UUID,
    commodity_names: list[str],
    role: str,
    lat: float,
    lon: float,
    qty_min: int,
    qty_max: int,
) -> None:
    """Build and store the IS vector for a test user directly via raw SQL."""
    vec = build_candidate_vector(
        commodity_list=commodity_names,
        role=role,
        lat=lat,
        lon=lon,
        qty_min=qty_min,
        qty_max=qty_max,
    )
    vec_literal = "[" + ",".join(str(v) for v in vec) + "]"
    db = SessionLocal()
    try:
        db.execute(
            text("""
                INSERT INTO user_embeddings (user_id, is_vector, updated_at)
                VALUES (CAST(:uid AS uuid), CAST(:vec AS vector), NOW())
                ON CONFLICT (user_id) DO UPDATE
                    SET is_vector  = EXCLUDED.is_vector,
                        updated_at = EXCLUDED.updated_at
            """),
            {"uid": str(user_id), "vec": vec_literal},
        )
        db.commit()
    finally:
        db.close()


def _mint_token(user_id: uuid.UUID, profile_id: int) -> str:
    return create_access_token(
        user_id=user_id,
        session_id=uuid.uuid4(),
        profile_id=profile_id,
    )


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _redis_seen_key(user_id: uuid.UUID) -> str:
    return f"rec:seen:{user_id}"


# ---------------------------------------------------------------------------
# Cleanup — DB rows and Redis keys
# ---------------------------------------------------------------------------

def _cleanup() -> None:
    db = SessionLocal()
    try:
        users = db.query(User).filter(
            User.phone_number.in_([USER_A_PHONE, USER_B_PHONE, USER_C_PHONE]),
            User.country_code == COUNTRY,
        ).all()
        for u in users:
            db.delete(u)
        db.commit()
        if users:
            print(f"[cleanup] Removed {len(users)} test user(s) from DB.")
    finally:
        db.close()


def _cleanup_redis(user_ids: list[uuid.UUID]) -> None:
    r = get_redis()
    for uid in user_ids:
        r.delete(_redis_seen_key(uid))
    print(f"[cleanup] Removed {len(user_ids)} Redis seen key(s).")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("\n" + "=" * 64)
    print("  RECOMMENDATION + REDIS SEEN SET — FULL API TEST")
    print("=" * 64)

    # Pre-run cleanup in case a previous run left debris
    _cleanup()

    # ── Setup ────────────────────────────────────────────────────────────────
    section("SETUP — Creating test users + embeddings in DB")

    a_uid, a_pid = _create_user_and_profile(
        phone=USER_A_PHONE, name="Arjun Traders",
        role_id=1, commodity_ids=[1, 2],           # Trader, Rice + Cotton
        lat=19.076, lon=72.877,
        city="Mumbai", state_name="Maharashtra",
        qty_min=100, qty_max=500,
    )
    b_uid, b_pid = _create_user_and_profile(
        phone=USER_B_PHONE, name="Bina Exports",
        role_id=3, commodity_ids=[1, 3],           # Exporter, Rice + Sugar
        lat=18.520, lon=73.856,
        city="Pune", state_name="Maharashtra",
        qty_min=200, qty_max=1000,
    )
    c_uid, c_pid = _create_user_and_profile(
        phone=USER_C_PHONE, name="Chetan Brokers",
        role_id=2, commodity_ids=[2, 3],           # Broker, Cotton + Sugar
        lat=19.099, lon=72.868,
        city="Thane", state_name="Maharashtra",
        qty_min=50, qty_max=300,
    )

    _insert_embedding(a_uid, ["rice", "cotton"], "trader",   19.076, 72.877, 100,  500)
    _insert_embedding(b_uid, ["rice", "sugar"],  "exporter", 18.520, 73.856, 200, 1000)
    _insert_embedding(c_uid, ["cotton", "sugar"],"broker",   19.099, 72.868,  50,  300)

    tok_a = _mint_token(a_uid, a_pid)
    tok_b = _mint_token(b_uid, b_pid)
    h_a, h_b = _h(tok_a), _h(tok_b)

    print(f"  User A (trader)   id={a_uid}")
    print(f"  User B (exporter) id={b_uid}")
    print(f"  User C (broker)   id={c_uid}")

    r = get_redis()

    try:
        # ====================================================================
        section("A. GET /recommendations/ — basic structure + pagination")
        # ====================================================================

        resp = client.get("/recommendations/", headers=h_a, params={"page": 1, "limit": 10})
        body = resp.json()
        show("GET /recommendations/?page=1&limit=10  (User A)", body)
        check("status 200",                     resp.status_code == 200,                    resp.status_code)
        check("has user_id",                    "user_id"         in body["data"])
        check("has role",                       "role"            in body["data"])
        check("has commodity",                  "commodity"       in body["data"])
        check("has qty_range",                  "qty_range"       in body["data"])
        check("has page",                       "page"            in body["data"])
        check("has limit",                      "limit"           in body["data"])
        check("has total_available",            "total_available" in body["data"])
        check("has has_more",                   "has_more"        in body["data"])
        check("has results array",              isinstance(body["data"]["results"], list))
        check("page = 1",                       body["data"]["page"] == 1,                  body["data"]["page"])
        check("limit = 10",                     body["data"]["limit"] == 10,                body["data"]["limit"])
        check("B + C in pool (total_available ≥ 2)",
              body["data"]["total_available"] >= 2,  body["data"]["total_available"])

        # Verify result shape
        if body["data"]["results"]:
            first = body["data"]["results"][0]
            for field in ["user_id", "name", "role", "commodity", "similarity",
                          "is_user_verified", "is_business_verified",
                          "quantity_min", "quantity_max", "business_name", "city", "state"]:
                check(f"result has field '{field}'", field in first)

        # Page 2
        resp2 = client.get("/recommendations/", headers=h_a, params={"page": 2, "limit": 10})
        check("page 2 → 200",                   resp2.status_code == 200,                   resp2.status_code)
        check("page 2 in response body",        resp2.json()["data"]["page"] == 2)

        # Unauthenticated → 401 / 403
        resp_unauth = client.get("/recommendations/")
        check("no token → 401 or 403",          resp_unauth.status_code in (401, 403),      resp_unauth.status_code)

        # ====================================================================
        section("B. Exclusion — already-following users filtered out")
        # ====================================================================

        # A follows B
        client.post(f"/connections/follow/{b_uid}", headers=h_a)

        resp = client.get("/recommendations/", headers=h_a, params={"page": 1, "limit": 50})
        body = resp.json()
        result_ids = [r_["user_id"] for r_ in body["data"]["results"]]
        show("GET /recommendations/ after A follows B", {"result_ids": result_ids[:5], "total": body["data"]["total_available"]})
        check("status 200",                     resp.status_code == 200)
        check("B absent from results (followed)",
              str(b_uid) not in result_ids,     str(b_uid))

        # Unfollow B to restore clean state for next section
        client.delete(f"/connections/follow/{b_uid}", headers=h_a)

        # ====================================================================
        section("C. Exclusion — already-requested users filtered out")
        # ====================================================================

        # A sends message request to C
        client.post(f"/connections/message-request/{c_uid}", headers=h_a)

        resp = client.get("/recommendations/", headers=h_a, params={"page": 1, "limit": 50})
        body = resp.json()
        result_ids = [r_["user_id"] for r_ in body["data"]["results"]]
        show("GET /recommendations/ after A requests C", {"result_ids": result_ids[:5], "total": body["data"]["total_available"]})
        check("status 200",                     resp.status_code == 200)
        check("C absent from results (requested)",
              str(c_uid) not in result_ids,     str(c_uid))

        # Withdraw request to restore clean state
        client.delete(f"/connections/message-request/{c_uid}", headers=h_a)

        # ====================================================================
        section("D. POST /recommendations/seen — stores seen set in Redis")
        # ====================================================================

        # Clean slate — ensure no leftover key
        r.delete(_redis_seen_key(a_uid))

        payload = {"user_ids": [str(b_uid), str(c_uid)]}
        resp = client.post("/recommendations/seen", headers=h_a, json=payload)
        show("POST /recommendations/seen  {B, C}", {"status": resp.status_code})
        check("status 204",                     resp.status_code == 204,                    resp.status_code)
        check("no response body",               resp.content == b"")

        # Verify Redis key exists
        key = _redis_seen_key(a_uid)
        check("Redis key created",              r.exists(key) == 1)

        # Verify both UUIDs are in the set
        members = {
            m.decode() if isinstance(m, bytes) else m
            for m in r.smembers(key)
        }
        check("B in Redis seen set",            str(b_uid) in members,  members)
        check("C in Redis seen set",            str(c_uid) in members,  members)
        check("set size = 2",                   len(members) == 2,      len(members))

        # ====================================================================
        section("E. GET /recommendations/ — seen users excluded")
        # ====================================================================

        resp = client.get("/recommendations/", headers=h_a, params={"page": 1, "limit": 50})
        body = resp.json()
        result_ids = [r_["user_id"] for r_ in body["data"]["results"]]
        show("GET /recommendations/ after marking B + C as seen", {
            "result_ids":      result_ids[:5],
            "total_available": body["data"]["total_available"],
        })
        check("status 200",                     resp.status_code == 200)
        check("B absent (in seen set)",         str(b_uid) not in result_ids,  str(b_uid))
        check("C absent (in seen set)",         str(c_uid) not in result_ids,  str(c_uid))

        # ====================================================================
        section("F. POST /recommendations/seen — TTL set once, not reset")
        # ====================================================================

        initial_ttl = r.ttl(key)
        check("TTL is set (> 0)",               initial_ttl > 0,                            initial_ttl)
        check("TTL ≤ 48 h (172800 s)",          initial_ttl <= _SEEN_TTL_SECONDS,           initial_ttl)
        check("TTL > 47 h (fresh key)",         initial_ttl > _SEEN_TTL_SECONDS - 3600,     initial_ttl)

        # Second POST — adds more IDs, TTL must NOT reset
        extra_id = str(uuid.uuid4())
        client.post("/recommendations/seen", headers=h_a, json={"user_ids": [extra_id]})
        ttl_after_second_call = r.ttl(key)

        # TTL should be ≤ initial_ttl (it counted down, not reset)
        check("TTL not reset after second POST",
              ttl_after_second_call <= initial_ttl,
              f"initial={initial_ttl}  after={ttl_after_second_call}")

        # Extra ID was added to the set
        members_after = {
            m.decode() if isinstance(m, bytes) else m
            for m in r.smembers(key)
        }
        check("extra ID added to set on second POST",
              extra_id in members_after,  members_after)
        check("set size = 3 after second POST",
              len(members_after) == 3,    len(members_after))

        # ====================================================================
        section("G. POST /recommendations/seen — validation")
        # ====================================================================

        # No token → 401 / 403
        resp_unauth = client.post("/recommendations/seen", json={"user_ids": [str(uuid.uuid4())]})
        check("no token → 401 or 403",          resp_unauth.status_code in (401, 403),      resp_unauth.status_code)

        # Exceeds max 50 IDs → 422
        too_many = {"user_ids": [str(uuid.uuid4()) for _ in range(51)]}
        resp_big = client.post("/recommendations/seen", headers=h_a, json=too_many)
        show("POST /recommendations/seen with 51 IDs (should be 422)", resp_big.json())
        check("51 IDs → 422 validation error",  resp_big.status_code == 422,                resp_big.status_code)

        # Empty list → 204 (no-op, accepted)
        resp_empty = client.post("/recommendations/seen", headers=h_a, json={"user_ids": []})
        check("empty list → 204",               resp_empty.status_code == 204,              resp_empty.status_code)

        # Invalid UUID → 422
        resp_bad = client.post("/recommendations/seen", headers=h_a, json={"user_ids": ["not-a-uuid"]})
        check("invalid UUID → 422",             resp_bad.status_code == 422,                resp_bad.status_code)

        # Exactly 50 IDs → 204
        exactly_50 = {"user_ids": [str(uuid.uuid4()) for _ in range(50)]}
        resp_50 = client.post("/recommendations/seen", headers=h_b, json=exactly_50)
        check("exactly 50 IDs → 204",           resp_50.status_code == 204,                 resp_50.status_code)

        # ====================================================================
        section("H. Redis key inspection")
        # ====================================================================

        # Key format
        expected_key = f"rec:seen:{a_uid}"
        check(f"Redis key format is 'rec:seen:{{user_id}}'",
              r.exists(expected_key) == 1,  expected_key)

        # TTL is still alive
        live_ttl = r.ttl(expected_key)
        check("TTL still positive (key not expired)",
              live_ttl > 0,  live_ttl)

        # B's seen key (from the exactly-50 test above)
        b_key = _redis_seen_key(b_uid)
        b_ttl = r.ttl(b_key)
        check("B's seen key has TTL set",       b_ttl > 0,  b_ttl)
        check("B's seen key TTL ≤ 48 h",        b_ttl <= _SEEN_TTL_SECONDS,  b_ttl)
        check("B's seen set has 50 members",    r.scard(b_key) == 50,  r.scard(b_key))

        # ====================================================================
        section("I. POST /recommendations/search — public custom search")
        # ====================================================================

        resp = client.post("/recommendations/search", json={
            "commodity":     ["rice", "cotton"],
            "role":          "trader",
            "latitude_raw":  19.076,
            "longitude_raw": 72.877,
            "qty_min_mt":    100,
            "qty_max_mt":    500,
        })
        body = resp.json()
        show("POST /recommendations/search  (public, no auth)", body)
        check("status 200",                     resp.status_code == 200,                    resp.status_code)
        check("has total",                      "total"   in body["data"])
        check("has results array",              isinstance(body["data"]["results"], list))

        if body["data"]["results"]:
            first = body["data"]["results"][0]
            check("result has similarity",      "similarity" in first)
            check("result has user_id",         "user_id"    in first)

        # No token required (public endpoint)
        resp_no_auth = client.post("/recommendations/search", json={
            "commodity": ["sugar"], "role": "broker",
            "latitude_raw": 18.5, "longitude_raw": 73.8,
            "qty_min_mt": 50, "qty_max_mt": 300,
        })
        check("public search without token → 200",
              resp_no_auth.status_code == 200,  resp_no_auth.status_code)

        # Missing required field → 422
        resp_bad = client.post("/recommendations/search", json={"role": "trader"})
        check("missing fields → 422",           resp_bad.status_code == 422,                resp_bad.status_code)

    finally:
        # Always clean up — DB rows and Redis keys
        _cleanup()
        _cleanup_redis([a_uid, b_uid, c_uid])

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"\n{'=' * 64}")
    print(f"  RESULTS:  {PASS_COUNT} passed   {FAIL_COUNT} failed")
    print(f"{'=' * 64}\n")

    if FAIL_COUNT:
        sys.exit(1)


if __name__ == "__main__":
    main()
