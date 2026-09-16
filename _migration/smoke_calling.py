#!/usr/bin/env python3
"""Calling integration smoke test — the parts fakes cannot prove.

The 41 unit tests in tests/test_calling.py drive in-memory fakes. They verify
our logic and nothing about the outside world. This script checks the three
things that can only fail against the real services:

  1. Stream accepts our user token format          (is the JWT shaped right?)
  2. Stream accepts our server token + REST calls  (provision, mark_ended)
  3. Firebase accepts a data-only push             (can we ring a phone at all?)

Run it ONCE after credentials are configured, before trusting anything else.

    python3 _migration/smoke_calling.py
    python3 _migration/smoke_calling.py --fcm-token <a real device token>

Needs STREAM_API_KEY and STREAM_API_SECRET in the environment or .env. The FCM
check is skipped unless a device token is passed, since there is no way to
verify delivery without a real handset.

Safe to run against production: it creates one throwaway call id, immediately
ends it, and sends at most one silent data push to a token you supply.
"""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
_results: list[tuple[str, str, str]] = []


def record(name: str, status: str, detail: str = "") -> None:
    _results.append((status, name, detail))
    mark = {PASS: "  PASS", FAIL: "  FAIL", SKIP: "  SKIP"}[status]
    print(f"{mark}  {name}" + (f": {detail}" if detail else ""))


# ── 1. Configuration ──────────────────────────────────────────────────────────

def check_config():
    from app.modules.calling.data.adapters.stream_video import StreamVideoProvider

    provider = StreamVideoProvider()
    if not provider.is_configured:
        record("stream credentials present", FAIL,
               "STREAM_API_KEY / STREAM_API_SECRET missing — calling will return 503")
        return None
    record("stream credentials present", PASS)
    return provider


# ── 2. User token ─────────────────────────────────────────────────────────────

def check_user_token(provider) -> tuple[str, str] | None:
    """Mint a token and decode it locally. A malformed token is rejected by the
    client SDK at join time, which is far too late to find out."""
    import jwt

    call_uuid = uuid.uuid4()
    user_id = uuid.uuid4()
    call_type, call_id = provider.new_call_id(call_uuid)

    try:
        creds = provider.issue_token(user_id, call_type, call_id)
    except Exception as exc:
        record("mint user token", FAIL, str(exc))
        return None

    claims = jwt.decode(creds.token, options={"verify_signature": False})
    problems = []
    if claims.get("user_id") != str(user_id):
        problems.append("user_id claim wrong")
    if "exp" not in claims:
        problems.append("no exp — token would never expire")
    expected_cid = f"{call_type}:{call_id}"
    if expected_cid not in (claims.get("call_cids") or []):
        problems.append(f"call_cids missing {expected_cid} — token would not be call-scoped")

    if problems:
        record("user token shape", FAIL, "; ".join(problems))
        return None
    record("user token shape", PASS, f"scoped to {expected_cid}, expires {creds.expires_at:%H:%M}")
    return call_type, call_id


# ── 3. Server REST: provision + mark_ended ────────────────────────────────────

def check_server_api(provider, call_type: str, call_id: str) -> None:
    """The real prize. If provisioning fails the hard duration cap never reaches
    Stream, and if mark_ended fails a forgotten call bills until that cap."""
    from app.modules.calling.domain.value_objects import MAX_CALL_DURATION_SECONDS

    ok = provider.provision_call(
        stream_call_type=call_type,
        stream_call_id=call_id,
        created_by_id=uuid.uuid4(),
        max_duration_seconds=MAX_CALL_DURATION_SECONDS,
    )
    if ok:
        record("provision call (sets max_duration cap)", PASS,
               f"cap = {MAX_CALL_DURATION_SECONDS // 3600}h")
    else:
        record("provision call (sets max_duration cap)", FAIL,
               "calls will run without Stream's own duration cap — see logs for the HTTP error")

    if provider.end_call_remote(call_type, call_id):
        record("mark_ended (stops billing)", PASS)
    else:
        record("mark_ended (stops billing)", FAIL,
               "sessions cannot be terminated server-side; forgotten calls would bill to the cap")


# ── 4. Push ───────────────────────────────────────────────────────────────────

def check_push(fcm_token: str | None) -> None:
    if not fcm_token:
        record("fcm data push", SKIP, "pass --fcm-token <device token> to test ringing")
        return

    from app.modules.calling.data.adapters.fcm import FcmPushSender
    from app.modules.calling.domain.entities import PushTarget

    sent = FcmPushSender().send_data(
        [PushTarget(user_id=uuid.uuid4(), fcm_token=fcm_token)],
        {"type": "smoke_test", "call_id": str(uuid.uuid4())},
    )
    if sent:
        record("fcm data push", PASS, "accepted by FCM — confirm the device received it")
    else:
        record("fcm data push", FAIL,
               "no push means no ringing on a backgrounded phone; check the service account "
               "has the messaging scope and, for iOS, that an APNs key is uploaded")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fcm-token", help="a real device token, to test push delivery")
    args = ap.parse_args()

    print("Calling integration smoke test\n" + "=" * 46)

    provider = check_config()
    if provider is not None:
        ids = check_user_token(provider)
        if ids is not None:
            check_server_api(provider, *ids)

    check_push(args.fcm_token)

    failed = sum(1 for s, _, _ in _results if s == FAIL)
    passed = sum(1 for s, _, _ in _results if s == PASS)
    skipped = sum(1 for s, _, _ in _results if s == SKIP)
    print("=" * 46)
    print(f"{passed} passed, {failed} failed, {skipped} skipped")
    if failed:
        print("\nCalling is NOT safe to enable until the failures above are resolved.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
