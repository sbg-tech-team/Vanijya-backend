"""A rejected document and an unreachable provider must not look the same.

For three months every verification attempt in production recorded
status="error" with the message "Your token is expired. This was a temporary
token to test the account" — the Surepass trial subscription had lapsed. The
app rendered that as "Failed" in red, so users were told their PAN had been
rejected when nobody had ever looked at it.

The cause: Surepass answers `success: false` both for a genuinely bad document
and for its own account problems, and the adapter called all of it
DocumentRejectedError.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.modules.verification.data.adapters import surepass  # noqa: E402
from app.modules.verification.domain.exceptions import (  # noqa: E402
    DocumentRejectedError,
    ProviderUnavailableError,
)

failures = []


def check(label, got, want):
    if got == want:
        print(f"  PASS  {label}")
    else:
        failures.append(label)
        print(f"  FAIL  {label}\n        got:  {got!r}\n        want: {want!r}")


def raises(fn):
    try:
        fn()
    except Exception as exc:
        return type(exc).__name__
    return "no exception"


def fake_response(status_code=200, body=None, text="", json_raises=False):
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    if json_raises:
        r.json.side_effect = ValueError("not json")
    else:
        r.json.return_value = body or {}
    return r


def call(**kw):
    with patch.dict("os.environ", {"SUREPASS_TOKEN": "t"}), \
         patch.object(surepass.requests, "post", return_value=fake_response(**kw)):
        return raises(lambda: surepass._post("/x", {}, "PAN"))


# ── the production incident ─────────────────────────────────────────────────
check("expired trial token is NOT a rejection",
      call(body={"success": False,
                 "message": "Your token is expired.This was a temporary token to "
                            "test the account, please consider upgrading to a paid "
                            "subscription."}),
      "ProviderUnavailableError")

# ── genuine rejections stay rejections ──────────────────────────────────────
check("an invalid document is a rejection",
      call(body={"success": False, "message": "No record found for this PAN"}),
      "DocumentRejectedError")

# ── everything else that is not a verdict ───────────────────────────────────
for label, kw, want in (
    ("401 credentials",   dict(status_code=401), "ProviderUnavailableError"),
    ("429 quota",         dict(status_code=429), "ProviderUnavailableError"),
    ("503 provider down", dict(status_code=503), "ProviderUnavailableError"),
    ("html error page",   dict(json_raises=True, text="<html>502</html>"),
                          "ProviderUnavailableError"),
):
    check(label, call(**kw), want)

with patch.dict("os.environ", {"SUREPASS_TOKEN": "t"}), \
     patch.object(surepass.requests, "post",
                  side_effect=surepass.requests.RequestException("timed out")):
    check("timeout is not a rejection",
          raises(lambda: surepass._post("/x", {}, "PAN")),
          "ProviderUnavailableError")

with patch.dict("os.environ", {"SUREPASS_TOKEN": ""}, clear=False):
    check("missing credentials is not a rejection",
          raises(lambda: surepass._post("/x", {}, "PAN")),
          "ProviderUnavailableError")

# ── the request must not be able to hang forever ────────────────────────────
with patch.dict("os.environ", {"SUREPASS_TOKEN": "t"}), \
     patch.object(surepass.requests, "post",
                  return_value=fake_response(body={"success": True, "data": {}})) as post:
    surepass._post("/x", {}, "PAN")
    check("every provider call has a timeout",
          post.call_args.kwargs.get("timeout") is not None, True)

# ── a happy path still returns the data block ───────────────────────────────
with patch.dict("os.environ", {"SUREPASS_TOKEN": "t"}), \
     patch.object(surepass.requests, "post",
                  return_value=fake_response(body={"success": True,
                                                   "data": {"pan_status": "EXISTING AND VALID"}})):
    check("success returns the data block",
          surepass._post("/x", {}, "PAN"), {"pan_status": "EXISTING AND VALID"})

if failures:
    sys.exit(f"\nFAIL - {len(failures)} check(s) failed: {failures}")
print("\nPASS - provider failures are told apart from document rejections")
