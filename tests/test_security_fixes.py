"""
tests/test_security_fixes.py

Tests for the broken-access-control fixes.

Coverage:
  1. Auth enforcement  — every protected endpoint returns 401 with no token
  2. Identity from token — user_id/me no longer a required query/path param
  3. Response envelope — all responses use ok() → {success, message, data}
  4. Status codes      — 201 creates, 204 deletes, 409 conflicts

Run:
    pytest tests/test_security_fixes.py -v
"""
import pytest
from uuid import uuid4, UUID
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from main import app
from app.dependencies import (
    CurrentUser,
    get_current_user,
    get_current_user_id,
    get_current_profile_id,
)

# ── Fixed mock identities ─────────────────────────────────────────────────────

MOCK_USER_ID    = uuid4()
MOCK_PROFILE_ID = 42

def _mock_user_id():    return MOCK_USER_ID
def _mock_profile_id(): return MOCK_PROFILE_ID
def _mock_current_user():
    return CurrentUser(user_id=MOCK_USER_ID, profile_id=MOCK_PROFILE_ID)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def anon():
    """Unauthenticated client — no dependency overrides."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def auth():
    """Authenticated client — auth dependencies bypassed via overrides."""
    app.dependency_overrides[get_current_user_id]    = _mock_user_id
    app.dependency_overrides[get_current_profile_id] = _mock_profile_id
    app.dependency_overrides[get_current_user]       = _mock_current_user
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


# ─────────────────────────────────────────────────────────────────────────────
# 1. AUTH ENFORCEMENT — 401 without token
# ─────────────────────────────────────────────────────────────────────────────

_gid = uuid4()
_aid = uuid4()
_tid = uuid4()   # target user uuid

PROTECTED_ENDPOINTS = [
    # Feed
    ("GET",    "/feed/home"),
    ("POST",   "/feed/engagement"),
    # News
    ("GET",    "/news/feed"),
    ("GET",    "/news/my/taste"),
    ("GET",    "/news/my/history"),
    ("GET",    "/news/saved"),
    ("GET",    f"/news/{_aid}"),
    ("POST",   f"/news/{_aid}/engage"),
    ("POST",   f"/news/{_aid}/like"),
    ("POST",   f"/news/{_aid}/save"),
    ("POST",   f"/news/{_aid}/share"),
    ("POST",   f"/news/{_aid}/comment"),
    # Groups
    ("GET",    "/api/v1/groups/"),
    ("POST",   "/api/v1/groups/"),
    ("GET",    "/api/v1/groups/suggestions"),
    ("GET",    f"/api/v1/groups/{_gid}"),
    ("PATCH",  f"/api/v1/groups/{_gid}"),
    ("POST",   f"/api/v1/groups/{_gid}/join"),
    ("DELETE", f"/api/v1/groups/{_gid}/leave"),
    ("GET",    f"/api/v1/groups/{_gid}/members"),
    ("POST",   f"/api/v1/groups/{_gid}/favorite"),
    ("POST",   f"/api/v1/groups/{_gid}/mute"),
    # Posts
    ("GET",    "/posts/"),
    ("GET",    "/posts/mine"),
    ("GET",    "/posts/following"),
    ("GET",    "/posts/saved"),
    ("POST",   "/posts/"),
    # Connections (new token-based paths)
    ("POST",   f"/connections/follow/{_tid}"),
    ("DELETE", f"/connections/follow/{_tid}"),
    ("GET",    f"/connections/follow/status/{_tid}"),
    ("POST",   f"/connections/message-request/{_tid}"),
    ("GET",    "/connections/message-requests/received"),
    ("GET",    "/connections/message-requests/sent"),
    ("GET",    "/connections/search"),
]


@pytest.mark.parametrize("method,path", PROTECTED_ENDPOINTS)
def test_401_without_token(anon, method, path):
    """Unauthenticated requests must be rejected with 401."""
    resp = getattr(anon, method.lower())(path)
    assert resp.status_code == 401, (
        f"FAIL  {method} {path}  →  got {resp.status_code}, expected 401"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. IDENTITY FROM TOKEN
#    Endpoints must work without a user_id query or path param.
#    Before the fix they returned 422 (missing required field).
# ─────────────────────────────────────────────────────────────────────────────

class TestIdentityFromToken:

    def test_feed_home_no_user_id_param(self, auth):
        # Patch where the function is used (router namespace), not where defined
        with patch("app.modules.feed.router.get_home_feed") as mock:
            mock.return_value = MagicMock(model_dump=lambda: {"items": []})
            resp = auth.get("/feed/home")
        assert resp.status_code != 422, "user_id is still being required as query param"

    def test_news_feed_no_user_id_param(self, auth):
        with patch("app.modules.news.router.get_news_feed") as mock:
            mock.return_value = MagicMock(model_dump=lambda: {"articles": []})
            resp = auth.get("/news/feed")
        assert resp.status_code != 422

    def test_groups_list_no_user_id_param(self, auth):
        with patch("app.modules.groups.router.list_groups") as mock:
            mock.return_value = {"groups": []}
            resp = auth.get("/api/v1/groups/")
        assert resp.status_code != 422

    def test_posts_feed_no_profile_id_param(self, auth):
        # Post router uses `service.get_feed` via module attr — patch the service
        with patch("app.modules.post.service.get_feed") as mock:
            mock.return_value = []
            resp = auth.get("/posts/")
        assert resp.status_code != 422

    def test_connections_search_no_me_param(self, auth):
        # connections_router uses service.search_users via module attr
        with patch("app.modules.connections.service.search_users") as mock:
            mock.return_value = []
            resp = auth.get("/connections/search")
        assert resp.status_code != 422

    def test_impersonation_blocked_feed(self, auth):
        """
        Passing ?user_id=<other_uuid> must not override the token's identity.
        The service must always receive MOCK_USER_ID from the token.
        """
        other_id = uuid4()
        captured = {}

        def fake_feed(db, user_id, cursor):
            captured["user_id"] = user_id
            return MagicMock(model_dump=lambda: {})

        with patch("app.modules.feed.router.get_home_feed", side_effect=fake_feed):
            auth.get(f"/feed/home?user_id={other_id}")

        if "user_id" in captured:
            assert captured["user_id"] == MOCK_USER_ID, (
                f"Impersonation still possible — service received {captured['user_id']} "
                f"instead of token's {MOCK_USER_ID}"
            )

    def test_old_connections_path_with_user_id_rejected(self, anon):
        """Old /{user_id}/follow/{target_id} pattern must no longer exist."""
        resp = anon.post(f"/connections/{uuid4()}/follow/{uuid4()}")
        assert resp.status_code == 404, (
            f"Old path-param route still exists — got {resp.status_code}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3. RESPONSE ENVELOPE
#    Every response must be: {"success": True, "message": str, "data": ...}
# ─────────────────────────────────────────────────────────────────────────────

def _assert_envelope(resp, expected_status=200):
    assert resp.status_code == expected_status, (
        f"Expected {expected_status}, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert "success" in body, f"Missing 'success' key: {body}"
    assert "message" in body, f"Missing 'message' key: {body}"
    assert "data"    in body, f"Missing 'data' key: {body}"
    assert body["success"] is True


class TestResponseEnvelope:

    def test_feed_home_envelope(self, auth):
        with patch("app.modules.feed.router.get_home_feed") as mock:
            mock.return_value = MagicMock(model_dump=lambda: {"items": []})
            resp = auth.get("/feed/home")
        _assert_envelope(resp)

    def test_news_feed_envelope(self, auth):
        with patch("app.modules.news.router.get_news_feed") as mock:
            mock.return_value = MagicMock(model_dump=lambda: {"articles": []})
            resp = auth.get("/news/feed")
        _assert_envelope(resp)

    def test_groups_list_envelope(self, auth):
        with patch("app.modules.groups.router.list_groups") as mock:
            mock.return_value = {"groups": []}
            resp = auth.get("/api/v1/groups/")
        _assert_envelope(resp)

    def test_connections_follow_status_envelope(self, auth):
        with patch("app.modules.connections.service.is_following") as mock:
            mock.return_value = False
            resp = auth.get(f"/connections/follow/status/{_tid}")
        _assert_envelope(resp)

    def test_connections_received_requests_envelope(self, auth):
        with patch("app.modules.connections.service.get_received_requests") as mock:
            mock.return_value = []
            resp = auth.get("/connections/message-requests/received")
        _assert_envelope(resp)

    def test_connections_followers_envelope(self, auth):
        # Public endpoint — no auth needed
        with patch("app.modules.connections.service.get_followers") as mock:
            mock.return_value = []
            resp = auth.get(f"/connections/{_tid}/followers")
        _assert_envelope(resp)

    def test_posts_feed_envelope(self, auth):
        with patch("app.modules.post.service.get_feed") as mock:
            mock.return_value = []
            resp = auth.get("/posts/")
        _assert_envelope(resp)


# ─────────────────────────────────────────────────────────────────────────────
# 4. HTTP STATUS CODES
# ─────────────────────────────────────────────────────────────────────────────

class TestStatusCodes:

    # ── 201 Creates ───────────────────────────────────────────────────────────

    def test_connections_follow_returns_201(self, auth):
        with patch("app.modules.connections.service.follow_user") as mock:
            mock.return_value = {"status": "following"}
            resp = auth.post(f"/connections/follow/{_tid}")
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}"

    def test_connections_message_request_returns_201(self, auth):
        with patch("app.modules.connections.service.send_message_request") as mock:
            mock.return_value = {"id": 1, "status": "pending"}
            resp = auth.post(f"/connections/message-request/{_tid}")
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}"

    def test_create_group_returns_201(self, auth):
        with patch("app.modules.groups.router.create_group") as mock:
            mock.return_value = {"id": str(uuid4()), "name": "test"}
            resp = auth.post("/api/v1/groups/", json={
                "name": "Test Group",
                "commodity": "wheat",
                "accessibility": "public",
            })
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"

    def test_create_post_returns_201(self, auth):
        with patch("app.modules.post.service.create_post", new_callable=AsyncMock) as mock:
            mock.return_value = {"id": 1}
            resp = auth.post("/posts/", json={
                "category_id": 1,
                "commodity_id": 1,
                "caption": "test post",
            })
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"

    def test_news_comment_returns_201(self, auth):
        with patch("app.modules.news.router.post_comment") as mock:
            mock.return_value = None
            resp = auth.post(f"/news/{_aid}/comment", json={"text": "hello"})
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}"

    def test_feed_engagement_returns_201(self, auth):
        with patch("app.modules.feed.router.submit_engagement") as mock:
            mock.return_value = {"recorded": 0}
            resp = auth.post("/feed/engagement", json={"signals": []})
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}"

    # ── 204 Deletes ───────────────────────────────────────────────────────────

    def test_delete_post_returns_204(self, auth):
        with patch("app.modules.post.service.delete_post", new_callable=AsyncMock):
            resp = auth.delete("/posts/1")
        assert resp.status_code == 204, f"Expected 204, got {resp.status_code}"

    def test_delete_post_comment_returns_204(self, auth):
        with patch("app.modules.post.service.delete_comment"):
            resp = auth.delete("/posts/1/comments/1")
        assert resp.status_code == 204, f"Expected 204, got {resp.status_code}"

    # ── 409 Conflicts ─────────────────────────────────────────────────────────

    def test_follow_already_following_returns_409(self, auth):
        from fastapi import HTTPException
        with patch("app.modules.connections.service.follow_user") as mock:
            mock.side_effect = HTTPException(status_code=409, detail="Already following.")
            resp = auth.post(f"/connections/follow/{_tid}")
        assert resp.status_code == 409, f"Expected 409, got {resp.status_code}"

    def test_duplicate_message_request_returns_409(self, auth):
        from fastapi import HTTPException
        with patch("app.modules.connections.service.send_message_request") as mock:
            mock.side_effect = HTTPException(status_code=409, detail="Already sent.")
            resp = auth.post(f"/connections/message-request/{_tid}")
        assert resp.status_code == 409, f"Expected 409, got {resp.status_code}"

    def test_duplicate_group_returns_409(self, auth):
        from app.modules.groups.service import GroupConflictError
        with patch("app.modules.groups.router.create_group") as mock:
            mock.side_effect = GroupConflictError("Already exists")
            resp = auth.post("/api/v1/groups/", json={
                "name": "Duplicate",
                "commodity": "wheat",
                "accessibility": "public",
            })
        assert resp.status_code == 409, f"Expected 409, got {resp.status_code}"

    # ── Route shape verification ───────────────────────────────────────────────

    def test_old_suggestions_path_gone(self, auth):
        """GET /api/v1/groups/suggestions/{uuid} must 404 — route was removed."""
        resp = auth.get(f"/api/v1/groups/suggestions/{uuid4()}")
        assert resp.status_code == 404, (
            f"Old /suggestions/{{user_id}} path still exists — got {resp.status_code}"
        )

    def test_new_suggestions_path_exists(self, auth):
        """GET /api/v1/groups/suggestions (no path param) must be reachable."""
        with patch("app.modules.groups.router.get_group_suggestions") as mock:
            mock.return_value = []
            resp = auth.get("/api/v1/groups/suggestions")
        assert resp.status_code != 404, "New /suggestions route not found"

    def test_old_connections_path_gone(self, anon):
        """Old /{user_id}/follow/{target_id} must 404 — anyone could impersonate."""
        resp = anon.post(f"/connections/{uuid4()}/follow/{uuid4()}")
        assert resp.status_code == 404, (
            f"Old path-param connections route still exists — got {resp.status_code}"
        )
