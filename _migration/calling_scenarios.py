#!/usr/bin/env python3
"""Every calling scenario I can construct, against a running service.

The 47 unit tests drive fakes and the smoke test proves Stream accepts us. This
covers the space in between: what the API does when two people race, when
somebody who is not in a call tries to act on it, when a call is already over,
when the callee has blocked the caller.

    BASE_URL=https://... SYNC_DATABASE_URL=... JWT_SECRET_KEY=... \
      python3 _migration/calling_scenarios.py

Creates real calls and ends every one of them. Safe to run against production,
but it does bill a few seconds of Stream time and leaves call history rows.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from uuid import uuid4

BASE = os.environ.get("BASE_URL", "https://vanijya-backend-7fuf.onrender.com").rstrip("/")

results: list[tuple[bool, str, str]] = []


def call(method: str, path: str, token: str | None = None, body: dict | None = None):
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body or {}).encode() if method != "GET" else None,
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {token}"} if token else {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, json.loads(r.read() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or "{}")
        except Exception:
            return e.code, {"raw": raw[:120].decode(errors="replace")}
    except Exception as exc:
        return 0, {"error": str(exc)[:120]}


def expect(label: str, got: int, allowed: set[int], note: str = ""):
    ok = got in allowed
    results.append((ok, label, f"got {got}, expected {sorted(allowed)}{' — ' + note if note else ''}"))
    print(f"  {'ok  ' if ok else 'FAIL'} {label:52} {got}")
    return ok


def data(payload):
    return payload.get("data", payload) if isinstance(payload, dict) else {}


def start_call(token, target, media="audio"):
    s, p = call("POST", "/calls", token, {"call_type": "dm", "target_user_id": target, "media": media})
    return s, data(p).get("call_id")


def cleanup(token, call_id):
    if call_id:
        call("POST", f"/calls/{call_id}/end", token, {})


# ── Actors ───────────────────────────────────────────────────────────────────
TOKENS = json.load(open("/tmp/actors.json"))
A, B, C = TOKENS["a"], TOKENS["b"], TOKENS["c"]

print(f"calling scenarios against {BASE}\n")

# ── Validation ───────────────────────────────────────────────────────────────
print("validation")
s, _ = call("POST", "/calls", A["token"], {"call_type": "dm", "media": "audio"})
expect("dm without target_user_id is rejected", s, {422})
s, _ = call("POST", "/calls", A["token"], {"call_type": "dm", "target_user_id": B["user_id"], "group_id": str(uuid4())})
expect("dm with a group_id is rejected", s, {422})
s, _ = call("POST", "/calls", A["token"], {"call_type": "group"})
expect("group without group_id is rejected", s, {422})
s, _ = call("POST", "/calls", A["token"], {"call_type": "carrier-pigeon", "target_user_id": B["user_id"]})
expect("unknown call_type is rejected", s, {422})
s, _ = call("POST", "/calls", A["token"], {"call_type": "dm", "target_user_id": B["user_id"], "media": "video"})
expect("video is refused while disabled", s, {400, 403, 409, 501})
s, _ = call("POST", "/calls", A["token"], {"call_type": "dm", "target_user_id": "not-a-uuid"})
expect("malformed uuid is rejected", s, {422})

# ── Who you may call ─────────────────────────────────────────────────────────
print("\nwho you may call")
s, cid = start_call(A["token"], A["user_id"])
expect("calling yourself is refused", s, {400, 403, 409, 422})
cleanup(A["token"], cid)
s, cid = start_call(A["token"], str(uuid4()))
expect("calling a user who does not exist is refused", s, {400, 403, 404, 422})
cleanup(A["token"], cid)

# ── Auth ─────────────────────────────────────────────────────────────────────
print("\nauthentication")
s, _ = call("POST", "/calls", None, {"call_type": "dm", "target_user_id": B["user_id"]})
expect("no token cannot start a call", s, {401, 403})
s, _ = call("GET", "/calls", None)
expect("no token cannot read history", s, {401, 403})
s, _ = call("POST", "/calls", "garbage.token.here", {"call_type": "dm", "target_user_id": B["user_id"]})
expect("a junk token cannot start a call", s, {401, 403})

# ── Lifecycle and third parties ──────────────────────────────────────────────
print("\nlifecycle")
s, cid = start_call(A["token"], B["user_id"])
expect("caller starts a call", s, {200, 201})

s, _ = call("POST", f"/calls/{cid}/token", B["token"], {})
expect("callee cannot get a token before accepting", s, {409, 403})
s, _ = call("POST", f"/calls/{cid}/accept", C["token"], {})
expect("a third party cannot accept", s, {403, 404})
s, _ = call("POST", f"/calls/{cid}/end", C["token"], {})
expect("a third party cannot end", s, {403, 404})
s, _ = call("POST", f"/calls/{cid}/heartbeat", C["token"], {})
expect("a third party cannot heartbeat", s, {403, 404})
s, _ = call("GET", f"/calls/{cid}", C["token"])
expect("a third party cannot read the call", s, {403, 404})
s, _ = call("POST", f"/calls/{cid}/accept", A["token"], {})
expect("the caller cannot accept their own call", s, {400, 403, 409})

s, _ = call("POST", f"/calls/{cid}/accept", B["token"], {})
expect("callee accepts", s, {200})
s, _ = call("POST", f"/calls/{cid}/accept", B["token"], {})
expect("accepting twice is refused", s, {400, 409})
s, _ = call("POST", f"/calls/{cid}/reject", B["token"], {})
expect("rejecting after accepting is refused", s, {400, 409})
s, _ = call("POST", f"/calls/{cid}/token", B["token"], {})
expect("callee gets a token after accepting", s, {200})
s, _ = call("POST", f"/calls/{cid}/heartbeat", B["token"], {})
expect("participant may heartbeat", s, {200, 204})

s, _ = call("POST", f"/calls/{cid}/end", A["token"], {})
expect("caller ends the call", s, {200})
s, _ = call("POST", f"/calls/{cid}/end", A["token"], {})
expect("ending twice is refused or idempotent", s, {200, 400, 409})
s, _ = call("POST", f"/calls/{cid}/heartbeat", B["token"], {})
expect("heartbeat on an ended call is refused", s, {400, 404, 409})
s, _ = call("POST", f"/calls/{cid}/token", B["token"], {})
expect("token on an ended call is refused", s, {400, 403, 404, 409})

# ── Unknown call ids ─────────────────────────────────────────────────────────
print("\nunknown call ids")
ghost = str(uuid4())
for action in ("accept", "reject", "end", "heartbeat", "token"):
    s, _ = call("POST", f"/calls/{ghost}/{action}", A["token"], {})
    expect(f"{action} on a call that does not exist", s, {403, 404})
s, _ = call("GET", f"/calls/{ghost}", A["token"])
expect("reading a call that does not exist", s, {403, 404})

# ── Concurrency ──────────────────────────────────────────────────────────────
print("\nconcurrency")
s1, c1 = start_call(A["token"], B["token"] and B["user_id"])
s2, c2 = start_call(A["token"], C["user_id"])
expect("a second outgoing call while one is ringing", s2, {200, 201, 409},
       "409 means busy is enforced; 2xx means it is allowed by design")
cleanup(A["token"], c1)
cleanup(A["token"], c2)

s3, c3 = start_call(A["token"], B["user_id"])
s4, c4 = start_call(B["token"], A["user_id"])
expect("both parties dial each other at once", s4, {200, 201, 409})
cleanup(A["token"], c3)
cleanup(B["token"], c4)

# ── Reject path ──────────────────────────────────────────────────────────────
print("\nreject path")
s, cid = start_call(A["token"], B["token"] and B["user_id"])
s, _ = call("POST", f"/calls/{cid}/reject", C["token"], {})
expect("a third party cannot reject", s, {403, 404})
s, _ = call("POST", f"/calls/{cid}/reject", B["token"], {})
expect("callee rejects", s, {200})
s, _ = call("POST", f"/calls/{cid}/accept", B["token"], {})
expect("accepting after rejecting is refused", s, {400, 409})
cleanup(A["token"], cid)

# ── Blocking ─────────────────────────────────────────────────────────────────
print("\nblocking")
s, _ = call("POST", f"/safety/block/{A['user_id']}", B["token"], {})
if s in (200, 201):
    s, cid = start_call(A["token"], B["user_id"])
    expect("a blocked user cannot be called", s, {400, 403, 404, 409})
    cleanup(A["token"], cid)
    call("DELETE", f"/safety/block/{A['user_id']}", B["token"], {})
    print("       (unblocked again)")
else:
    print(f"  skip block scenario — could not block (HTTP {s})")

# ── Usage ────────────────────────────────────────────────────────────────────
print("\nbudget")
s, p = call("GET", "/calls/usage", A["token"])
expect("usage is readable", s, {200})
u = data(p)
ok = all(k in u for k in ("user_minutes_today", "user_daily_limit"))
results.append((ok, "usage reports minutes and the limit", str(list(u))[:70]))
print(f"  {'ok  ' if ok else 'FAIL'} usage reports minutes and the limit")

# ── Summary ──────────────────────────────────────────────────────────────────
passed = sum(1 for ok, _, _ in results if ok)
failed = [(l, d) for ok, l, d in results if not ok]
print(f"\n{'=' * 62}\n{passed}/{len(results)} scenarios behaved correctly")
if failed:
    print("\nnot as expected:")
    for label, detail in failed:
        print(f"  - {label}: {detail}")
    sys.exit(1)
