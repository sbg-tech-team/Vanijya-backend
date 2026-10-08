"""
tests/test_viewer_names.py

People's names shown in the viewer's app language (X-App-Language), and kept
as typed — or in the recipient's own language — in what is pushed to others.
No DB.

    pytest tests/test_viewer_names.py -v
"""
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.request_language import (
    RequestLanguageMiddleware,
    get_viewer_language,
    no_viewer_language,
    viewer_language,
)
from app.modules.translation.domain.names import name_for_viewer

AKSHAY = {"en": "Akshay", "hi": "अक्षय", "auto": ["hi"]}


def _app():
    app = FastAPI()
    app.add_middleware(RequestLanguageMiddleware)

    @app.get("/name")
    def sync_endpoint():                      # sync: runs in the threadpool
        return {"lang": get_viewer_language(), "name": name_for_viewer("Akshay", AKSHAY)}

    @app.get("/name-async")
    async def async_endpoint():
        return {"lang": get_viewer_language(), "name": name_for_viewer("Akshay", AKSHAY)}

    return TestClient(app)


def test_header_decides_the_name_in_sync_and_async_endpoints():
    client = _app()
    for path in ("/name", "/name-async"):
        assert client.get(path, headers={"X-App-Language": "hi"}).json() == {"lang": "hi", "name": "अक्षय"}
        assert client.get(path, headers={"X-App-Language": "hi-IN"}).json()["name"] == "अक्षय"
        assert client.get(path, headers={"X-App-Language": "en"}).json()["name"] == "Akshay"
        assert client.get(path).json() == {"lang": None, "name": "Akshay"}          # no header: as typed
        assert client.get(path, headers={"X-App-Language": "gu"}).json()["name"] == "Akshay"  # none stored: as typed
        assert client.get(path, headers={"X-App-Language": "<script>"}).json()["lang"] is None


def test_language_does_not_leak_between_requests():
    client = _app()
    client.get("/name", headers={"X-App-Language": "hi"})
    assert client.get("/name").json()["lang"] is None


def test_pushes_keep_names_as_typed_or_in_the_recipients_language():
    with viewer_language("hi"):                     # the sender's request
        assert name_for_viewer("Akshay", AKSHAY) == "अक्षय"
        with no_viewer_language():                  # building a push to others
            assert name_for_viewer("Akshay", AKSHAY) == "Akshay"
        with viewer_language("en"):                 # built for one recipient
            assert name_for_viewer("Akshay", AKSHAY) == "Akshay"
        assert name_for_viewer("Akshay", AKSHAY) == "अक्षय"   # restored afterwards


def test_name_typed_in_hindi_shown_in_english_to_english_viewers():
    tathagat = {"hi": "तथागत", "en": "Tathagata"}
    with viewer_language("en"):
        assert name_for_viewer("तथागत", tathagat) == "Tathagata"
    with viewer_language("hi"):
        assert name_for_viewer("तथागत", tathagat) == "तथागत"


# ── Incoming call: each callee sees the caller in their own language ────────

def _call_from_alice(bob_lang):
    from tests.test_calling import ALICE, BOB, FakeRepo, _start

    repo = FakeRepo()
    plain = repo.get_user_snap

    def get_user_snap(uid):
        snap = plain(uid)
        if snap and uid == ALICE:
            snap.name_i18n = {"en": "Alice", "hi": "एलिस", "auto": ["hi"]}
        return snap

    repo.get_user_snap = get_user_snap
    # The real repository builds participants from profile rows, which carry
    # name_i18n; the shared fake builds them from a plain name table.
    plain_create = repo.create_call

    def create_call(**kw):
        call = plain_create(**kw)
        for p in call.participants:
            if p.user_id == ALICE:
                p.name_i18n = {"en": "Alice", "hi": "एलिस", "auto": ["hi"]}
        return call

    repo.create_call = create_call
    repo.app_langs = {BOB: bob_lang} if bob_lang else {}
    return ALICE, _start(repo)


def test_incoming_call_shows_the_caller_in_the_callees_language():
    alice, dispatch = _call_from_alice("hi")
    [push] = dispatch.pushes
    assert push.data["caller_name"] == "एलिस"
    [event] = dispatch.socket_events
    names = {p["user_id"]: p["name"] for p in event.payload["participants"]}
    assert names[str(alice)] == "एलिस"


def test_incoming_call_for_an_english_callee_stays_english():
    _, dispatch = _call_from_alice("en")
    assert dispatch.pushes[0].data["caller_name"] == "Alice"
    _, dispatch = _call_from_alice(None)          # no saved language: as typed
    assert dispatch.pushes[0].data["caller_name"] == "Alice"
