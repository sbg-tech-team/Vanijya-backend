"""Onboarding (app_old `auth`) contract test.
    python3.12 _migration/test_onboarding.py
"""
import _boot  # noqa: F401
import os, sys
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.onboarding.application.use_cases.verify_otp import split_phone
from app.modules.onboarding.domain.entities import DevProfileRef, SessionRef, UserRef
from app.modules.onboarding.domain.exceptions import InvalidFirebaseTokenError
from app.modules.onboarding.domain.interfaces.firebase import IFirebaseVerifier
from app.modules.onboarding.domain.interfaces.repository import IOnboardingRepository
from app.modules.onboarding.presentation.dependencies import (
    get_firebase_verifier, get_onboarding_repo)
from app.modules.onboarding.presentation.router import router

UID = UUID("11111111-1111-1111-1111-111111111111")


class FakeRepo(IOnboardingRepository):
    def __init__(self):
        self.user = None; self.profile = None; self.session = None
        self.profile_id = None; self.added = []; self.rotated = []; self.deactivated = []
    def find_user_by_phone(self, cc, pn):            return self.user
    def get_profile_id_for_user(self, user_id):      return self.profile_id
    def find_profile_by_name(self, name):            return self.profile
    def add_session(self, **kw):                     self.added.append(kw)
    def get_active_session_by_refresh_hash(self, h): return self.session
    def rotate_refresh_token(self, sid, h, t):       self.rotated.append((sid, h))
    def deactivate_session(self, sid):               self.deactivated.append(sid)
    def deactivate_all_sessions(self, uid):          self.deactivated.append(uid)


class FakeFirebase(IFirebaseVerifier):
    def __init__(self, claims=None, boom=False): self.claims, self.boom = claims, boom
    def verify_id_token(self, t):
        if self.boom: raise InvalidFirebaseTokenError("Invalid Firebase token: bad")
        return self.claims


def client(repo=None, fb=None):
    repo = repo or FakeRepo()
    app = FastAPI(); app.include_router(router)
    app.dependency_overrides[get_onboarding_repo] = lambda: repo
    app.dependency_overrides[get_firebase_verifier] = lambda: (fb or FakeFirebase({"phone_number": "+919876543210"}))
    return TestClient(app), repo


fails = []
def check(label, got, want):
    if got != want: fails.append(f"  {label}\n     got:  {got!r}\n     want: {want!r}")

check("route set", sorted(f"{sorted(r.methods)[0]} {r.path}" for r in router.routes),
      ["GET /auth/dev-token", "POST /auth/firebase-verify",
       "POST /auth/logout", "POST /auth/refresh"])

# --- app_old's exact phone-splitting rule -------------------------------------
check("split +91", split_phone("+919876543210"), ("9876543210", "+91"))
check("split other", split_phone("+14155550100"), ("155550100", "+14"))

# --- firebase-verify: brand-new user -----------------------------------------
c, repo = client()
r = c.post("/auth/firebase-verify", json={"firebase_id_token": "t"})
check("new user 200", r.status_code, 200)
check("new user envelope", sorted(r.json()), ["data", "message", "success"])
check("new user message", r.json()["message"],
      "OTP verified. Use the onboarding token to complete registration.")
check("new user is_new_user", r.json()["data"]["is_new_user"], True)
check("new user has onboarding_token", bool(r.json()["data"]["onboarding_token"]), True)
check("new user no access_token", r.json()["data"]["access_token"], None)
check("new user creates no session", repo.added, [])

# --- user exists but never finished onboarding -------------------------------
c, repo = client(); repo.user = UserRef(user_id=UID, profile_id=None)
r = c.post("/auth/firebase-verify", json={"firebase_id_token": "t"})
check("no-profile is_new_user", r.json()["data"]["is_new_user"], True)
check("no-profile has onboarding_token", bool(r.json()["data"]["onboarding_token"]), True)
check("no-profile creates no session", repo.added, [])

# --- returning user -----------------------------------------------------------
c, repo = client(); repo.user = UserRef(user_id=UID, profile_id=42)
r = c.post("/auth/firebase-verify", json={"firebase_id_token": "t", "device_info": "pixel"})
d = r.json()["data"]
check("returning message", r.json()["message"], "Welcome back.")
check("returning is_new_user", d["is_new_user"], False)
check("returning has tokens", (bool(d["access_token"]), bool(d["refresh_token"])), (True, True))
check("returning user_id", d["user_id"], str(UID))
check("returning profile_id", d["profile_id"], 42)
check("returning expires_in is seconds", isinstance(d["expires_in"], int) and d["expires_in"] > 0, True)
check("session persisted once", len(repo.added), 1)
check("device_info stored", repo.added[0]["device_info"], "pixel")
check("refresh token is hashed not raw",
      repo.added[0]["refresh_token_hash"] != d["refresh_token"]
      and len(repo.added[0]["refresh_token_hash"]) == 64, True)

# --- bad firebase token -> 401 ------------------------------------------------
c, _ = client(fb=FakeFirebase(boom=True))
r = c.post("/auth/firebase-verify", json={"firebase_id_token": "t"})
check("bad token -> 401", r.status_code, 401)
check("bad token detail", r.json()["detail"], "Invalid Firebase token: bad")

# --- token with no phone claim -> 401 ----------------------------------------
c, _ = client(fb=FakeFirebase({"uid": "x"}))
r = c.post("/auth/firebase-verify", json={"firebase_id_token": "t"})
check("no phone -> 401", r.status_code, 401)
check("no phone detail", r.json()["detail"],
      "Token does not contain a phone number — wrong sign-in method?")

# --- refresh ------------------------------------------------------------------
c, repo = client()
repo.session = SessionRef(uuid4(), UID, datetime.now(timezone.utc) + timedelta(days=5))
repo.profile_id = 42
r = c.post("/auth/refresh", json={"refresh_token": "raw"})
check("refresh 200", r.status_code, 200)
check("refresh keys (NOT ok-wrapped)", sorted(r.json()),
      ["access_token", "expires_in", "refresh_token", "token_type"])
check("refresh rotated", len(repo.rotated), 1)
check("rotated hash != old", repo.rotated[0][1] != "raw", True)

c, repo = client()   # unknown token
r = c.post("/auth/refresh", json={"refresh_token": "raw"})
check("unknown refresh -> 401", r.status_code, 401)
check("unknown refresh detail", r.json()["detail"], "Invalid or revoked refresh token.")

c, repo = client()   # expired
repo.session = SessionRef(uuid4(), UID, datetime.now(timezone.utc) - timedelta(days=1))
r = c.post("/auth/refresh", json={"refresh_token": "raw"})
check("expired refresh -> 401", r.status_code, 401)
check("expired detail", r.json()["detail"], "Refresh token has expired. Please sign in again.")
check("expired deactivates session", len(repo.deactivated), 1)

c, repo = client()   # no profile
repo.session = SessionRef(uuid4(), UID, datetime.now(timezone.utc) + timedelta(days=5))
r = c.post("/auth/refresh", json={"refresh_token": "raw"})
check("no profile -> 401", r.status_code, 401)
check("no profile detail", r.json()["detail"], "User profile not found.")

# --- logout: invalid token is still a success --------------------------------
c, repo = client()
r = c.post("/auth/logout", json={}, headers={"Authorization": "Bearer garbage"})
check("logout bad token 200", r.status_code, 200)
check("logout bad token message", r.json()["message"], "Logged out.")
check("logout bad token revokes nothing", repo.deactivated, [])

# --- dev-token is DEBUG-gated -------------------------------------------------
os.environ["DEBUG"] = "false"
c, repo = client(); repo.profile = DevProfileRef(7, UID, "test1")
check("dev-token blocked when DEBUG off", c.get("/auth/dev-token", params={"name": "test1"}).status_code, 404)
os.environ["DEBUG"] = "true"
r = c.get("/auth/dev-token", params={"name": "test1"})
check("dev-token 200 when DEBUG on", r.status_code, 200)
check("dev-token keys", sorted(r.json()), ["access_token", "name", "profile_id", "user_id"])
check("dev-token profile_id", r.json()["profile_id"], 7)
c2, repo2 = client()
check("dev-token unknown name -> 404", c2.get("/auth/dev-token", params={"name": "nope"}).status_code, 404)
check("dev-token unknown detail", c2.get("/auth/dev-token", params={"name": "nope"}).json()["detail"],
      "No profile found with name 'nope'")
os.environ.pop("DEBUG", None)

# --- the import-time firebase crash must be gone ------------------------------
import importlib
mod = importlib.import_module("app.modules.onboarding.data.adapters.firebase")
check("firebase init is lazy (no app built at import)", mod._app, None)

if fails:
    print("FAIL\n" + "\n".join(fails)); sys.exit(1)
print("PASS - onboarding contract matches app_old (4 routes, 3 verify branches, refresh rotation, 401s, DEBUG gate, lazy firebase)")
