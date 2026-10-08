"""
tests/test_names.py

A person's name per language (profile.name_i18n) and the name-suggestions
endpoint. No DB, no live engine.

    pytest tests/test_names.py -v
"""
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_current_or_onboarding_user_id
from app.modules.translation.application.use_cases.name_suggestions import NameSuggestionsUseCase
from app.modules.translation.domain.exceptions import TranslationEngineUnavailableError
from app.modules.translation.domain.names import (
    clean_owner_names,
    display_name,
    merge_owner_names,
    names_to_generate,
    script_language,
    with_generated,
)


# ── Which language a typed name is in ─────────────────────────────────────────

def test_script_language_follows_the_script_not_the_app():
    assert script_language("Tathagata") == "en"
    assert script_language("तथागत") == "hi"
    assert script_language("R K शर्मा") == "hi"            # most letters decide
    assert script_language("ગૌરી") == "gu"
    assert script_language("123 !!") is None


# ── Storing names: the owner's spellings win ──────────────────────────────────

def test_create_with_hindi_typed_name_and_owner_english():
    got = merge_owner_names("तथागत", {"en": "Tathagata"}, existing=None, name_changed=True)
    assert got == {"hi": "तथागत", "en": "Tathagata"}          # no "auto": both are the owner's


def test_create_with_english_name_only():
    assert merge_owner_names("Akshay", None, existing=None, name_changed=True) == {"en": "Akshay"}


def test_editing_the_name_drops_generated_spellings_but_not_owner_ones():
    existing = {"en": "Akshay", "hi": "अक्षय", "auto": ["hi"]}
    # Name changed, nothing sent: the generated Hindi was made from the old name.
    assert merge_owner_names("Akshaya", None, existing, name_changed=True) == {"en": "Akshaya"}
    # Name unchanged, owner corrects the Hindi: it becomes theirs.
    got = merge_owner_names("Akshay", {"hi": "अक्शय"}, existing, name_changed=False)
    assert got == {"en": "Akshay", "hi": "अक्शय"}


def test_clean_owner_names_validates():
    assert clean_owner_names({"en": "  Gauri   Patel "}) == {"en": "Gauri Patel"}
    for bad in ({"xx": "a"}, {"en": ""}, {"en": 5}, {"en": "a" * 101}, {"auto": "x"}):
        with pytest.raises(ValueError):
            clean_owner_names(bad)


def test_names_to_generate_and_with_generated():
    assert names_to_generate("Akshay", None, ("en", "hi")) == ["hi"]
    assert names_to_generate("तथागत", {"hi": "तथागत", "en": "Tathagata"}, ("en", "hi")) == []
    # Stored entry made from an older name -> everything is stale.
    assert names_to_generate("Akshaya", {"en": "Akshay", "hi": "अक्षय"}, ("en", "hi")) == ["hi"]

    got = with_generated({"en": "Akshay"}, "hi", "अक्षय")
    assert got == {"en": "Akshay", "hi": "अक्षय", "auto": ["hi"]}
    # Generation never overwrites the owner's own spelling.
    assert with_generated({"hi": "तथागत", "en": "Tathagata"}, "en", "Tathagat")["en"] == "Tathagata"


def test_display_name_uses_the_viewers_language_else_as_typed():
    n = {"hi": "तथागत", "en": "Tathagata"}
    assert display_name("तथागत", n, "en") == "Tathagata"
    assert display_name("तथागत", n, "hi") == "तथागत"
    assert display_name("Akshay", {"en": "Akshay"}, "hi") == "Akshay"   # no Hindi yet
    assert display_name("Akshay", None, None) == "Akshay"


# ── Suggestions ───────────────────────────────────────────────────────────────

class FakeEngine:
    def __init__(self, suggestions=None, configured=True, fail=False):
        self.suggestions = suggestions or []
        self.configured = configured
        self.fail = fail
        self.calls = 0

    @property
    def is_configured(self):
        return self.configured

    def translate_fields(self, prompt):
        self.calls += 1
        if self.fail:
            raise RuntimeError("down")
        return {"suggestions": self.suggestions}


class FakeCache:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ttl_seconds):
        self.store[key] = value


def test_hindi_name_gets_english_spellings_screened_for_sound():
    engine = FakeEngine(["Gauri", "Gouri", "Gaura", "Gauri", "गौरी"])
    src, got = NameSuggestionsUseCase(engine, FakeCache()).execute("गौरी", "en")
    # "Gaura" changes the ending -> dropped; duplicate and wrong-script dropped.
    assert src == "hi" and got == ["Gauri", "Gouri"]


def test_strict_spelling_always_comes_first():
    # A final "a" variant may be offered (the person picks), never first.
    engine = FakeEngine(["Akshaya", "Akshay", "Akshai"])
    _, got = NameSuggestionsUseCase(engine, FakeCache()).execute("अक्षय", "en")
    assert got[:2] == ["Akshay", "Akshai"] and got[-1] == "Akshaya"


def test_english_name_gets_hindi_spellings():
    engine = FakeEngine(["अक्षय", "अक्षया", "अक्शय"])
    _, got = NameSuggestionsUseCase(engine, FakeCache()).execute("Akshay", "hi")
    assert got[0] == "अक्षय" and "अक्षया" not in got


def test_cached_answers_are_free_and_not_rate_limited():
    engine, cache, limited = FakeEngine(["Gauri"]), FakeCache(), []
    uc = NameSuggestionsUseCase(engine, cache)
    uc.execute("गौरी", "en", before_engine_call=lambda: limited.append(1))
    uc.execute("  गौरी ", "en", before_engine_call=lambda: limited.append(1))
    assert engine.calls == 1 and limited == [1]


def test_same_script_no_engine_and_bad_input():
    engine = FakeEngine()
    uc = NameSuggestionsUseCase(engine, FakeCache())
    assert uc.execute("Akshay", "en") == ("en", ["Akshay"]) and engine.calls == 0
    for text, to in (("", "en"), ("123", "en"), ("Akshay", "xx"), ("a" * 101, "hi")):
        with pytest.raises(ValueError):
            uc.execute(text, to)


def test_engine_down_gives_empty_list_unconfigured_raises():
    assert NameSuggestionsUseCase(FakeEngine(fail=True), FakeCache()).execute("गौरी", "en") == ("hi", [])
    with pytest.raises(TranslationEngineUnavailableError):
        NameSuggestionsUseCase(FakeEngine(configured=False), FakeCache()).execute("गौरी", "en")


def test_endpoint():
    from app.core.redis_client import get_redis
    from app.modules.translation.presentation.dependencies import get_name_suggestions_uc
    from app.modules.translation.presentation.router import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_or_onboarding_user_id] = lambda: uuid4()
    app.dependency_overrides[get_redis] = lambda: None
    app.dependency_overrides[get_name_suggestions_uc] = lambda: NameSuggestionsUseCase(
        FakeEngine(["Tathagat"]), FakeCache())
    client = TestClient(app)

    r = client.post("/translate/name-suggestions", json={"text": "तथागत", "to": "en"})
    assert r.status_code == 200
    assert r.json() == {"source_lang": "hi", "to": "en", "suggestions": ["Tathagat"]}
    assert client.post("/translate/name-suggestions", json={"text": "तथागत", "to": "xx"}).status_code == 422
    assert client.post("/translate/name-suggestions", json={"text": "", "to": "en"}).status_code == 422
    assert client.post("/translate/name-suggestions", json={"text": "123", "to": "en"}).status_code == 422



def test_suggestions_offer_the_final_a_variant_generation_never_does():
    from app.modules.translation.domain.transliteration import decide, sounds_the_same
    # Suggestions: the person picks, so Tathagat and Tathagata are both offered.
    engine = FakeEngine(["Tathagat", "Tathagata"])
    assert NameSuggestionsUseCase(engine, FakeCache()).execute("तथागत", "en")[1] ==         ["Tathagat", "Tathagata"]
    engine = FakeEngine(["तथागत"])
    assert NameSuggestionsUseCase(engine, FakeCache()).execute("Tathagata", "hi")[1] == ["तथागत"]
    # Generation stays strict: no guessing a silent final vowel.
    assert sounds_the_same("Tathagata", "तथागत") is not None
    # A changed vowel is never offered, even in suggestions.
    engine = FakeEngine(["Akshay", "Akshaye", "Akshayi"])
    assert NameSuggestionsUseCase(engine, FakeCache()).execute("अक्षय", "en")[1] == ["Akshay"]
