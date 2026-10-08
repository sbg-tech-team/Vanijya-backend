"""
tests/test_app_language.py

GET/PUT /auth/app-language — the language the user runs the app in.
Use case with an in-memory repository; endpoints with dependencies
overridden. No DB.

    pytest tests/test_app_language.py -v
"""
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_current_or_onboarding_user_id
from app.modules.onboarding.application.use_cases.app_language import AppLanguageUseCase
from app.modules.onboarding.domain.exceptions import UserNotCreatedError


class FakeRepo:
    def __init__(self, users=()):
        self.langs = {u: "en" for u in users}

    def get_app_language(self, user_id):
        return self.langs.get(user_id)

    def set_app_language(self, user_id, app_language):
        if user_id not in self.langs:
            return False
        self.langs[user_id] = app_language
        return True


def test_defaults_to_english_and_can_be_set_to_hindi():
    uid = uuid4()
    uc = AppLanguageUseCase(FakeRepo([uid]))
    assert uc.get(uid) == "en"
    assert uc.set(uid, "hi") == "hi"
    assert uc.get(uid) == "hi"


def test_only_supported_languages_are_accepted():
    uid = uuid4()
    uc = AppLanguageUseCase(FakeRepo([uid]))
    for bad in ("gu", "xx", "", "hindi"):
        with pytest.raises(ValueError):
            uc.set(uid, bad)


def test_before_the_user_row_exists_it_says_so():
    uc = AppLanguageUseCase(FakeRepo())
    with pytest.raises(UserNotCreatedError):
        uc.get(uuid4())
    with pytest.raises(UserNotCreatedError):
        uc.set(uuid4(), "hi")


def _client(repo, user_id):
    from app.modules.onboarding.presentation.dependencies import get_app_language_uc
    from app.modules.onboarding.presentation.router import router
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_or_onboarding_user_id] = lambda: user_id
    app.dependency_overrides[get_app_language_uc] = lambda: AppLanguageUseCase(repo)
    return TestClient(app)


def test_endpoints_round_trip():
    uid = uuid4()
    repo = FakeRepo([uid])
    client = _client(repo, uid)

    r = client.get("/auth/app-language")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["app_language"] == "en" and set(data["supported"]) == {"en", "hi"}

    r = client.put("/auth/app-language", json={"app_language": " HI "})
    assert r.status_code == 200 and r.json()["data"]["app_language"] == "hi"
    assert repo.langs[uid] == "hi"


def test_endpoint_errors():
    uid = uuid4()
    client = _client(FakeRepo([uid]), uid)
    assert client.put("/auth/app-language", json={"app_language": "gu"}).status_code == 422
    assert client.put("/auth/app-language", json={}).status_code == 422
    assert _client(FakeRepo(), uid).put("/auth/app-language", json={"app_language": "hi"}).status_code == 404


def test_dual_token_dependency_accepts_both_token_kinds():
    from app.core.security.jwt_handler import create_access_token, create_onboarding_token
    uid = uuid4()
    assert get_current_or_onboarding_user_id(create_access_token(uid, uuid4(), 1)) == uid
    assert get_current_or_onboarding_user_id(create_onboarding_token(uid, "9876543210", "+91")) == uid
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        get_current_or_onboarding_user_id("not-a-token")
