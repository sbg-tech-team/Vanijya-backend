"""Verification contract test — locks app_old behaviour, especially the
"provider rejection is a 200 with status=error, NOT a 4xx" rule.
    python3.12 _migration/test_verification.py
"""
import _boot  # noqa: F401
import sys
from datetime import datetime, timezone
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import CurrentUser, get_current_user
from app.modules.verification.domain.entities import DocRecord, ProfileRef, VerificationOutcome
from app.modules.verification.domain.exceptions import DocumentRejectedError
from app.modules.verification.domain.interfaces.repository import IVerificationRepository
from app.modules.verification.domain.interfaces.verifier import IDocumentVerifier
from app.modules.verification.presentation.dependencies import (
    get_document_verifier, get_verification_repo)
from app.modules.verification.presentation.router import router

ME  = UUID("11111111-1111-1111-1111-111111111111")
NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


class FakeRepo(IVerificationRepository):
    def __init__(self, profile=None):
        self.profile, self.saved, self.records = profile, [], []
    def get_profile_by_user(self, user_id): return self.profile
    def save_verification(self, **kw):
        self.saved.append(kw)
        return VerificationOutcome(kw["document_type"], kw["status"],
                                   kw["verified_at"])
    def list_records(self, profile_id): return self.records


class FakeVerifier(IDocumentVerifier):
    def __init__(self, reject=None): self.reject, self.calls = reject, []
    def verify(self, document_type, document_number, **kw):
        self.calls.append((document_type, document_number, kw))
        if document_type == "aadhaar": raise NotImplementedError("nope")
        if self.reject: raise DocumentRejectedError(self.reject)
        return "surepass", {"ok": True}


def client(profile=None, reject=None):
    repo, ver = FakeRepo(profile), FakeVerifier(reject)
    app = FastAPI(); app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(user_id=ME, profile_id=1)
    app.dependency_overrides[get_verification_repo] = lambda: repo
    app.dependency_overrides[get_document_verifier] = lambda: ver
    return TestClient(app), repo, ver


fails = []
def check(label, got, want):
    if got != want: fails.append(f"  {label}\n     got:  {got!r}\n     want: {want!r}")

check("route set", sorted(f"{sorted(r.methods)[0]} {r.path}" for r in router.routes),
      ["GET /verification/status", "POST /verification/kyb/gst",
       "POST /verification/kyb/iec", "POST /verification/kyc/aadhaar",
       "POST /verification/kyc/pan"])

TRADER_KYC_OK = ProfileRef(profile_id=5, role_id=1, is_user_verified=True, is_business_verified=False)
TRADER_NO_KYC = ProfileRef(profile_id=5, role_id=1, is_user_verified=False, is_business_verified=False)
EXPORTER      = ProfileRef(profile_id=6, role_id=3, is_user_verified=True, is_business_verified=False)
PAN = {"id_number": "ABCDE1234F", "name": "Bob", "dob": "1990-01-01"}

# --- happy path: envelope + message ------------------------------------------
c, repo, ver = client(TRADER_NO_KYC)
r = c.post("/verification/kyc/pan", json=PAN)
check("pan 200", r.status_code, 200)
check("pan envelope", sorted(r.json()), ["data", "message", "success"])
check("pan message", r.json()["message"], "PAN verification complete.")
check("pan data keys", sorted(r.json()["data"]), ["document_type", "status", "verified_at"])
check("pan status verified", r.json()["data"]["status"], "verified")
check("pan marks profile", repo.saved[0]["mark_profile_verified"], True)
check("pan category", repo.saved[0]["category"], "kyc")
check("verifier got name+dob", ver.calls[0][2], {"name": "Bob", "dob": "1990-01-01"})

# --- provider rejection: 200 with status=error, NOT 4xx ----------------------
c, repo, ver = client(TRADER_NO_KYC, reject="PAN is not valid: INVALID")
r = c.post("/verification/kyc/pan", json=PAN)
check("rejection is 200 not 4xx", r.status_code, 200)
check("rejection status=error", r.json()["data"]["status"], "error")
check("rejection verified_at None", r.json()["data"]["verified_at"], None)
check("rejection stores message", repo.saved[0]["error_message"], "PAN is not valid: INVALID")
check("rejection does NOT flag profile", repo.saved[0]["mark_profile_verified"], False)

# --- KYB before KYC -> 400 ----------------------------------------------------
c, repo, _ = client(TRADER_NO_KYC)
r = c.post("/verification/kyb/gst", json={"gstin": "22AAAAA0000A1Z5"})
check("kyb before kyc -> 400", r.status_code, 400)
check("kyb before kyc detail", r.json()["detail"],
      "Complete identity verification (KYC) before verifying your business.")
check("nothing persisted", repo.saved, [])

# --- role rule: exporter must use iec, not gst -------------------------------
c, repo, _ = client(EXPORTER)
r = c.post("/verification/kyb/gst", json={"gstin": "22AAAAA0000A1Z5"})
check("exporter gst -> 400", r.status_code, 400)
check("exporter gst detail", r.json()["detail"],
      "Exporter must use 'iec' for business verification, not 'gst'.")
check("trader iec -> 400", client(TRADER_KYC_OK)[0].post(
      "/verification/kyb/iec", json={"iec_number": "IEC1"}).json()["detail"],
      "Trader must use 'gst' for business verification, not 'iec'.")

# --- valid KYB ----------------------------------------------------------------
c, repo, _ = client(TRADER_KYC_OK)
r = c.post("/verification/kyb/gst", json={"gstin": "22AAAAA0000A1Z5"})
check("gst 200", r.status_code, 200)
check("gst message", r.json()["message"], "GST verification complete.")
check("gst category", repo.saved[0]["category"], "kyb")
c, repo, _ = client(EXPORTER)
check("iec message", c.post("/verification/kyb/iec", json={"iec_number": "IEC1"}).json()["message"],
      "IEC verification complete.")

# --- aadhaar is 501 and must never reach the provider ------------------------
c, repo, ver = client(TRADER_KYC_OK)
r = c.post("/verification/kyc/aadhaar", json={"aadhaar_number": "123412341234"})
check("aadhaar 501", r.status_code, 501)
check("aadhaar detail", r.json()["detail"],
      "Aadhaar verification is not yet available. API provider TBD.")
check("aadhaar never calls provider", ver.calls, [])

# --- no profile -> 404 on every endpoint -------------------------------------
c, _, _ = client(None)
for path, body in [("/verification/kyc/pan", PAN),
                   ("/verification/kyb/gst", {"gstin": "x"}),
                   ("/verification/kyb/iec", {"iec_number": "x"})]:
    check(f"no profile {path} -> 404", c.post(path, json=body).status_code, 404)
check("no profile detail", c.post("/verification/kyc/pan", json=PAN).json()["detail"],
      "Profile not found. Complete onboarding first.")
check("no profile status -> 404", c.get("/verification/status").status_code, 404)

# --- status shape -------------------------------------------------------------
c, repo, _ = client(TRADER_KYC_OK)
repo.records = [DocRecord("kyc", "pan", "verified", NOW)]
r = c.get("/verification/status")
check("status 200", r.status_code, 200)
check("status keys", sorted(r.json()), ["kyb", "kyc"])
check("status kyc", r.json()["kyc"],
      {"status": "verified", "document_type": "pan", "verified_at": "2026-01-02T03:04:05Z"})
check("status kyb not_submitted", r.json()["kyb"],
      {"status": "not_submitted", "document_type": None, "verified_at": None})

# --- validation ---------------------------------------------------------------
check("missing pan field -> 422",
      client(TRADER_KYC_OK)[0].post("/verification/kyc/pan", json={"id_number": "X"}).status_code, 422)

if fails:
    print("FAIL\n" + "\n".join(fails)); sys.exit(1)
print("PASS - verification contract matches app_old (5 routes, rejection=200/error, 400 rules, 501, 404)")
