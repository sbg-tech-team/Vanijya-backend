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


# ── Generation (profile.name_i18n backfill) ───────────────────────────────────

from app.modules.translation.application.use_cases.generate_profile_names import (  # noqa: E402
    GenerateProfileNamesUseCase,
)
from app.modules.translation.domain.interfaces.profile_names_repository import ProfileName  # noqa: E402
from app.modules.translation.domain.names import with_failed  # noqa: E402


class GenEngine:
    """Answers per prompt kind: {"hi": ...} for English names, {"en": ...} for Devanagari."""

    def __init__(self, to_hi=None, to_en=None, fail=False):
        self.to_hi, self.to_en, self.fail = to_hi or {}, to_en or {}, fail
        self.prompts = []

    is_configured = True

    def translate_fields(self, prompt):
        import json
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("down")
        names = json.loads(prompt.user_content.split("Names:\n", 1)[1])
        table = self.to_hi if "Devanagari script) so that" in prompt.system_instruction else self.to_en
        return {k: table[v] for k, v in names.items() if v in table}


class MemProfiles:
    def __init__(self, rows):
        self.rows = {r.profile_id: r for r in rows}
        self.saved = {}
        self.edited_meanwhile = set()

    def profiles_missing_names(self, targets, limit):
        return list(self.rows.values())[:limit]

    def get(self, profile_id):
        return self.rows.get(profile_id)

    def save_if_unchanged(self, before, name_i18n):
        if before.profile_id in self.edited_meanwhile:
            return False
        self.saved[before.profile_id] = name_i18n
        return True


def test_generation_english_to_hindi_accepts_and_marks_failures():
    repo = MemProfiles([
        ProfileName(1, "Akshay", {"en": "Akshay"}),
        ProfileName(2, "Kavya", {"en": "Kavya"}),          # engine writes काव्य: ambiguous ending
        ProfileName(3, "Rahul", None),                      # low confidence
    ])
    engine = GenEngine(to_hi={
        "Akshay": {"hi": "अक्षय", "confidence": 0.95},
        "Kavya": {"hi": "काव्य", "confidence": 0.95},
        "Rahul": {"hi": "राहुल", "confidence": 0.6},
    })
    stats = GenerateProfileNamesUseCase(repo, engine).run()
    assert repo.saved[1] == {"en": "Akshay", "hi": "अक्षय", "auto": ["hi"]}
    assert repo.saved[2] == {"en": "Kavya", "failed": ["hi"]}
    assert repo.saved[3] == {"en": "Rahul", "failed": ["hi"]}       # seeded with the typed name
    assert stats["accepted"] == 1 and stats["rejected"] == 2 and len(engine.prompts) == 1


def test_generation_hindi_to_english_never_adds_a_final_a():
    repo = MemProfiles([
        ProfileName(1, "अक्षय", {"hi": "अक्षय"}),
        ProfileName(2, "तथागत", {"hi": "तथागत"}),
    ])
    engine = GenEngine(to_en={
        "अक्षय": {"en": "Akshaya", "confidence": 0.95},       # would change the name
        "तथागत": {"en": "Tathagat", "confidence": 0.9},
    })
    GenerateProfileNamesUseCase(repo, engine).run()
    assert repo.saved[1] == {"hi": "अक्षय", "failed": ["en"]}
    assert repo.saved[2] == {"hi": "तथागत", "en": "Tathagat", "auto": ["en"]}


def test_generation_outage_marks_nothing_and_owner_edits_win():
    repo = MemProfiles([ProfileName(1, "Akshay", {"en": "Akshay"})])
    stats = GenerateProfileNamesUseCase(repo, GenEngine(fail=True)).run()
    assert repo.saved == {} and stats["engine_errors"] == 1          # retried next run

    repo.edited_meanwhile.add(1)
    engine = GenEngine(to_hi={"Akshay": {"hi": "अक्षय", "confidence": 0.95}})
    stats = GenerateProfileNamesUseCase(repo, engine).run()
    assert repo.saved == {} and stats["skipped_changed"] == 1


def test_generation_skips_failed_and_marks_unsupported_scripts():
    # Already failed for this name: not sent again.
    assert names_to_generate("Rahul", {"en": "Rahul", "failed": ["hi"]}, ("en", "hi")) == []
    # A new name clears the failure.
    assert merge_owner_names("Rahul K", None, {"en": "Rahul", "failed": ["hi"]}, name_changed=True) == {"en": "Rahul K"}
    # Owner typing their own spelling clears it too.
    got = merge_owner_names("Rahul", {"hi": "राहुल"}, {"en": "Rahul", "failed": ["hi"]}, name_changed=False)
    assert got == {"en": "Rahul", "hi": "राहुल"}
    # A script we cannot read at all (Odia is not offered): marked, no engine call.
    repo = MemProfiles([ProfileName(1, "ଗୌରୀ", None)])
    engine = GenEngine()
    GenerateProfileNamesUseCase(repo, engine).run()
    assert repo.saved[1] == {"failed": ["en", "hi"]} and engine.prompts == []


def test_generation_for_one_profile_and_with_generated_clears_failed():
    repo = MemProfiles([ProfileName(7, "Pooja", None)])
    engine = GenEngine(to_hi={"Pooja": {"hi": "पूजा", "confidence": 0.95}})
    GenerateProfileNamesUseCase(repo, engine).for_profile(7)
    assert repo.saved[7] == {"en": "Pooja", "hi": "पूजा", "auto": ["hi"]}
    assert with_generated(with_failed({"en": "X"}, "hi"), "hi", "एक्स") == {"en": "X", "hi": "एक्स", "auto": ["hi"]}


# ── All Indian scripts: exact conversion and the Tamil/Urdu route ─────────────

from app.modules.translation.domain.script_convert import to_devanagari  # noqa: E402


@pytest.mark.parametrize("typed, lang, devanagari", [
    ("ગૌરી", "gu", "गौरी"), ("હિરેન પટેલ", "gu", "हिरेन पटेल"),
    ("ਹਰਪ੍ਰੀਤ ਸਿੰਘ", "pa", "हरप्रीत सिंह"),            # Hindi writes Singh as सिंह
    ("ਸੱਤ", "pa", "सत्त"),                              # addak doubles the consonant
    ("সৌরভ গাঙ্গুলী", "bn", "सौरभ गांगुली"),           # nasal before consonant -> anusvara
    ("শরৎ", "bn", "शरत्"),
    ("వెంకటేష్", "te", "वेंकटेष्"), ("ಕಾರ್ತಿಕ್", "kn", "कार्तिक्"), ("ಅಕ್ಷಯ", "kn", "अक्षय"),
    ("അർജുൻ", "ml", "अर्जुन्"), ("മേനോൻ", "ml", "मेनोन्"),           # chillu letters
])
def test_same_family_scripts_convert_exactly(typed, lang, devanagari):
    assert to_devanagari(typed, lang) == devanagari


def test_conversion_refuses_what_it_cannot_map():
    assert to_devanagari("கார்த்திக்", "ta") is None        # Tamil: not letter-for-letter
    assert to_devanagari("ગૌરી", "hi") is None              # wrong source language
    assert to_devanagari("ગૌ\u0aF1રી", "gu") is None        # a Gujarati sign with no equivalent


def test_gujarati_name_gets_exact_hindi_and_checked_english():
    repo = MemProfiles([ProfileName(1, "ગૌરી", {"gu": "ગૌરી"})])
    engine = GenEngine(to_en={"गौरी": {"en": "Gauri", "confidence": 0.9}})
    GenerateProfileNamesUseCase(repo, engine).run()
    assert repo.saved[1] == {"gu": "ગૌરી", "hi": "गौरी", "en": "Gauri", "auto": ["en", "hi"]}
    # Only the English went to the engine — the Hindi was converted by rule.
    assert len(engine.prompts) == 1 and "Devanagari), in ENGLISH" in engine.prompts[0].system_instruction


class BothEngine(GenEngine):
    def __init__(self, answers):
        super().__init__()
        self.answers = answers

    def translate_fields(self, prompt):
        import json
        self.prompts.append(prompt)
        names = json.loads(prompt.user_content.split("Names:\n", 1)[1])
        return {k: self.answers[v] for k, v in names.items() if v in self.answers}


def test_tamil_name_accepted_only_when_hindi_and_english_agree():
    repo = MemProfiles([
        ProfileName(1, "கார்த்திக்", None),
        ProfileName(2, "அக்ஷய்", None),
        ProfileName(3, "முருகன்", None),
    ])
    engine = BothEngine({
        "கார்த்திக்": {"hi": "कार्तिक", "en": "Karthik", "confidence": 0.9},
        "அக்ஷய்": {"hi": "अक्षय", "en": "Akshaya", "confidence": 0.95},   # pair disagrees
        "முருகன்": {"hi": "मुरुगन", "en": "Murugan", "confidence": 0.5},   # too unsure
    })
    GenerateProfileNamesUseCase(repo, engine).run()
    assert repo.saved[1] == {"ta": "கார்த்திக்", "hi": "कार्तिक", "en": "Karthik", "auto": ["en", "hi"]}
    assert repo.saved[2] == {"ta": "அக்ஷய்", "failed": ["en", "hi"]}
    assert repo.saved[3] == {"ta": "முருகன்", "failed": ["en", "hi"]}


def test_suggestions_for_same_family_scripts():
    engine = FakeEngine(["Gauri", "Gaura"])
    uc = NameSuggestionsUseCase(engine, FakeCache())
    # To Hindi: the exact conversion, instantly, no engine call.
    assert uc.execute("ગૌરી", "hi") == ("gu", ["गौरी"]) and engine.calls == 0
    # To English: engine candidates checked against that exact Devanagari.
    assert uc.execute("ગૌરી", "en") == ("gu", ["Gauri"])
