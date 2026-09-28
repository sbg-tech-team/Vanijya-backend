"""
tests/test_content_translation.py

On-command translation of posts, comments and news. No DB, no live Gemini —
repository, engine and lock are in-memory fakes, so these run standalone.

    pytest tests/test_content_translation.py -v
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import CurrentUser, get_current_user, get_current_user_id
from app.modules.translation.application.use_cases.resolve_content_language import (
    ResolveContentLanguageUseCase,
)
from app.modules.translation.application.use_cases.translate_content import TranslateContentUseCase
from app.modules.translation.domain.content import (
    ContentRef,
    ContentSource,
    StoredTranslation,
    TranslationShapeError,
    field_hash,
    split_fresh,
    validate_shape,
)
from app.modules.translation.domain.content_prompt import (
    CONTENT_SYSTEM_INSTRUCTION,
    assemble_content_prompt,
)
from app.modules.translation.domain.exceptions import (
    LanguageNotChosenError,
    TranslationEngineUnavailableError,
)
from app.modules.translation.domain.value_objects import CONTENT_WAIT_SECONDS


# ── Fakes ──────────────────────────────────────────────────────────────────────

@dataclass
class FakeContentRepo:
    sources: dict = field(default_factory=dict)   # key -> ContentSource
    stored: dict = field(default_factory=dict)    # (key, lang) -> {field: (hash, text)}
    saves: list = field(default_factory=list)
    load_calls: int = 0
    # Called on every load — lets a test simulate another request storing a
    # translation while this one waits on the lock.
    on_load: Optional[object] = None

    def add(self, entity_type, entity_id, context=None, **fields):
        ref = ContentRef(entity_type, str(entity_id))
        self.sources[ref.key] = ContentSource(ref=ref, fields=fields, context=context)
        return ref

    def store(self, ref, lang, **fields):
        self.stored.setdefault((ref.key, lang), {}).update(
            {k: (field_hash(v_src), v_tr) for k, (v_src, v_tr) in fields.items()}
        )

    def load(self, refs, target_lang, viewer_profile_id):
        self.load_calls += 1
        if self.on_load:
            self.on_load(self.load_calls)
        out = {}
        for ref in refs:
            src = self.sources.get(ref.key)
            if src is None:
                continue
            # The request's field narrowing lives on the ref, not the source.
            src = ContentSource(ref=ref, fields=src.fields, context=src.context)
            out[ref.key] = (src, StoredTranslation(dict(self.stored.get((ref.key, target_lang), {}))))
        return out

    def save_fields(self, ref, target_lang, fields):
        self.saves.append((ref.key, target_lang, dict(fields)))
        self.stored.setdefault((ref.key, target_lang), {}).update(fields)


class FakeEngine:
    """Translates by prefixing '[lang]'. `mangle` lets a test corrupt output."""

    def __init__(self, configured=True, fail=False, mangle=None):
        self._configured = configured
        self.fail = fail
        self.mangle = mangle
        self.prompts = []

    @property
    def is_configured(self):
        return self._configured

    def translate_fields(self, prompt):
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("engine down")
        import json
        items = json.loads(prompt.user_content.split("Items:\n", 1)[1])
        out = {
            key: {name: ([f"[tr] {x}" for x in v] if isinstance(v, list) else f"[tr] {v}")
                  for name, v in fields.items()}
            for key, fields in items.items()
        }
        return self.mangle(out) if self.mangle else out


class FakeLock:
    def __init__(self, held=()):
        self.held = set(held)
        self.acquired = []
        self.released = []

    def acquire(self, key, ttl_seconds):
        if key in self.held:
            return False
        self.held.add(key)
        self.acquired.append(key)
        return True

    def release(self, key):
        self.held.discard(key)
        self.released.append(key)


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def make_uc(repo, engine=None, lock=None, clock=None):
    clock = clock or FakeClock()
    return TranslateContentUseCase(
        repository=repo, engine=engine or FakeEngine(), lock=lock or FakeLock(),
        sleep=clock.sleep, clock=clock,
    )


# ── Domain ─────────────────────────────────────────────────────────────────────

def test_field_hash_is_stable_and_content_sensitive():
    assert field_hash("wheat up") == field_hash("wheat up")
    assert field_hash("wheat up") != field_hash("wheat down")
    assert field_hash(["a", "b"]) != field_hash(["b", "a"])


def test_wanted_fields_ignores_unknown_and_defaults_to_all():
    assert ContentRef("post", "1").wanted_fields() == ("title", "caption")
    assert ContentRef("post", "1", fields=("caption", "password")).wanted_fields() == ("caption",)
    assert ContentRef("news", "x", fields=("title", "summary_bullets")).wanted_fields() == (
        "title", "summary_bullets")


def test_split_fresh_treats_edited_source_as_stale():
    ref = ContentRef("post", "1")
    src = ContentSource(ref=ref, fields={"title": "New title", "caption": "Same caption"})
    stored = StoredTranslation({
        "title": (field_hash("Old title"), "पुराना"),
        "caption": (field_hash("Same caption"), "वही"),
    })
    ready, todo = split_fresh(src, stored)
    assert ready == {"caption": "वही"}
    assert todo == {"title": "New title"}


def test_validate_shape_rejects_changed_shape():
    sent = {"title": "t", "summary_bullets": ["a", "b", "c"]}
    assert validate_shape(sent, {"title": "x", "summary_bullets": ["1", "2", "3"]})
    for bad in (
        None,
        {"title": "x"},                                          # dropped a field
        {"title": "x", "summary_bullets": ["1", "2", "3"], "extra": "y"},
        {"title": "x", "summary_bullets": ["1 2", "3"]},        # merged bullets
        {"title": "", "summary_bullets": ["1", "2", "3"]},      # empty text
        {"title": ["x"], "summary_bullets": ["1", "2", "3"]},   # wrong kind
    ):
        with pytest.raises(TranslationShapeError):
            validate_shape(sent, bad)


def test_prompt_static_part_never_varies_and_context_is_separate():
    a = ContentSource(ContentRef("post", "1"), {"title": "Wheat"}, context="Deal: wheat 10 MT")
    b = ContentSource(ContentRef("news", "n"), {"title": "Rice"})
    p1 = assemble_content_prompt(items=[(a, {"title": "Wheat"})], target_lang="hi")
    p2 = assemble_content_prompt(items=[(b, {"title": "Rice"})], target_lang="gu")
    assert p1.system_instruction == p2.system_instruction == CONTENT_SYSTEM_INSTRUCTION
    assert "Hindi" in p1.user_content and "Gujarati" in p2.user_content
    assert "Deal: wheat 10 MT" in p1.user_content.split("Items:")[0]
    assert "Context" not in p2.user_content
    assert p1.structured_output


# ── Language resolution ────────────────────────────────────────────────────────

class _PrefRepo:
    def __init__(self, default=None):
        self.default = default

    def get_default_target_lang(self, user_id):
        return self.default


def test_language_chain():
    uid = uuid4()
    assert ResolveContentLanguageUseCase(_PrefRepo("mr")).execute(uid, "ta", "gu") == "ta"
    assert ResolveContentLanguageUseCase(_PrefRepo("mr")).execute(uid, None, "gu-IN") == "gu"
    # App in English -> the reader's saved preference, not English.
    assert ResolveContentLanguageUseCase(_PrefRepo("mr")).execute(uid, None, "en") == "mr"
    assert ResolveContentLanguageUseCase(_PrefRepo("mr")).execute(uid, None, None) == "mr"
    # Unsupported header is ignored, not trusted.
    assert ResolveContentLanguageUseCase(_PrefRepo("mr")).execute(uid, None, "xx") == "mr"


def test_language_not_chosen_when_app_english_and_no_preference():
    with pytest.raises(LanguageNotChosenError):
        ResolveContentLanguageUseCase(_PrefRepo(None)).execute(uuid4(), None, "en")


# ── Translate use case ─────────────────────────────────────────────────────────

def test_stored_translation_is_served_without_engine_or_rate_limit():
    repo = FakeContentRepo()
    ref = repo.add("post", 1, title="Wheat up", caption="Buy now")
    repo.store(ref, "hi", title=("Wheat up", "गेहूं ऊपर"), caption=("Buy now", "अभी खरीदें"))
    engine, calls = FakeEngine(), []

    [res] = make_uc(repo, engine).execute(1, [ref], "hi", before_engine_call=lambda: calls.append(1))

    assert res.status == "ready" and res.cached
    assert res.fields == {"title": "गेहूं ऊपर", "caption": "अभी खरीदें"}
    assert engine.prompts == [] and calls == []


def test_miss_calls_engine_once_saves_with_hash_and_rate_limits_once():
    repo = FakeContentRepo()
    ref = repo.add("post", 1, title="Wheat up", caption="Buy now")
    engine, lock, calls = FakeEngine(), FakeLock(), []

    [res] = make_uc(repo, engine, lock).execute(1, [ref], "hi", before_engine_call=lambda: calls.append(1))

    assert res.status == "ready" and not res.cached
    assert res.fields == {"title": "[tr] Wheat up", "caption": "[tr] Buy now"}
    assert len(engine.prompts) == 1 and calls == [1]
    [(key, lang, saved)] = repo.saves
    assert key == "post:1" and lang == "hi"
    assert saved["title"] == (field_hash("Wheat up"), "[tr] Wheat up")
    assert lock.released == lock.acquired == ["content_translate:post:1:hi"]


def test_second_reader_same_language_pays_nothing():
    repo = FakeContentRepo()
    ref = repo.add("news", "n1", title="Rice export ban", summary_bullets=["a", "b"])
    engine = FakeEngine()
    make_uc(repo, engine).execute(1, [ref], "hi")
    [res] = make_uc(repo, engine).execute(2, [ref], "hi")
    assert res.cached and len(engine.prompts) == 1


def test_only_missing_fields_are_sent():
    repo = FakeContentRepo()
    ref = repo.add("post", 1, title="Wheat up", caption="Edited caption")
    repo.store(ref, "hi", title=("Wheat up", "गेहूं ऊपर"), caption=("Old caption", "पुराना"))
    engine = FakeEngine()

    [res] = make_uc(repo, engine).execute(1, [ref], "hi")

    assert '"caption": "Edited caption"' in engine.prompts[0].user_content
    assert "Wheat up" not in engine.prompts[0].user_content.split("Items:")[1]
    assert res.fields == {"title": "गेहूं ऊपर", "caption": "[tr] Edited caption"}


def test_news_card_request_does_not_pay_for_detail_fields():
    repo = FakeContentRepo()
    repo.add("news", "n1", title="T", description="long description",
             summary_bullets=["a"], impact_explanation="why")
    engine = FakeEngine()
    ref = ContentRef("news", "n1", fields=("title", "summary_bullets"))

    [res] = make_uc(repo, engine).execute(1, [ref], "hi")

    assert set(res.fields) == {"title", "summary_bullets"}
    assert "long description" not in engine.prompts[0].user_content


def test_items_are_batched_per_engine_call():
    repo = FakeContentRepo()
    refs = [repo.add("comment", i, content=f"c{i}") for i in range(7)]
    engine = FakeEngine()
    results = make_uc(repo, engine).execute(1, refs, "hi")
    assert [r.status for r in results] == ["ready"] * 7
    assert len(engine.prompts) == 2   # 5 + 2


def test_bad_output_for_one_item_is_not_stored_others_are():
    repo = FakeContentRepo()
    good = repo.add("comment", 1, content="fine")
    bad = repo.add("news", "n", title="T", summary_bullets=["a", "b"])

    def mangle(out):
        out["news:n"]["summary_bullets"] = ["merged a b"]
        return out

    res_good, res_bad = make_uc(repo, FakeEngine(mangle=mangle)).execute(1, [good, bad], "hi")
    assert res_good.status == "ready"
    assert res_bad.status == "failed"
    assert [s[0] for s in repo.saves] == ["comment:1"]


def test_engine_failure_reports_failed_and_releases_lock():
    repo = FakeContentRepo()
    ref = repo.add("post", 1, title="t", caption="c")
    lock = FakeLock()
    [res] = make_uc(repo, FakeEngine(fail=True), lock).execute(1, [ref], "hi")
    assert res.status == "failed"
    assert lock.released == lock.acquired and not lock.held


def test_rate_limit_rejection_releases_locks():
    repo = FakeContentRepo()
    ref = repo.add("post", 1, title="t", caption="c")
    lock = FakeLock()

    def limited():
        raise RuntimeError("429")

    with pytest.raises(RuntimeError):
        make_uc(repo, FakeEngine(), lock).execute(1, [ref], "hi", before_engine_call=limited)
    assert not lock.held


def test_concurrent_reader_waits_for_holder_instead_of_paying():
    repo = FakeContentRepo()
    ref = repo.add("post", 1, title="t", caption="c")
    lock = FakeLock(held={"content_translate:post:1:hi"})
    engine = FakeEngine()

    def other_request_finishes(n):
        if n == 3:  # the holder stores it while we poll
            repo.store(ref, "hi", title=("t", "टी"), caption=("c", "सी"))

    repo.on_load = other_request_finishes
    [res] = make_uc(repo, engine, lock).execute(1, [ref], "hi")

    assert res.status == "ready" and res.cached
    assert engine.prompts == []


def test_waiter_gives_up_with_in_progress():
    repo = FakeContentRepo()
    ref = repo.add("post", 1, title="t", caption="c")
    lock = FakeLock(held={"content_translate:post:1:hi"})
    clock = FakeClock()

    [res] = make_uc(repo, FakeEngine(), lock, clock).execute(1, [ref], "hi")

    assert res.status == "in_progress"
    assert clock.t >= CONTENT_WAIT_SECONDS


def test_not_found_and_duplicates():
    repo = FakeContentRepo()
    ref = repo.add("comment", 1, content="hello")
    missing = ContentRef("post", "999")
    results = make_uc(repo).execute(1, [ref, missing, ref], "hi")
    assert [r.status for r in results] == ["ready", "not_found"]


def test_unconfigured_engine_raises_only_when_needed():
    repo = FakeContentRepo()
    cached = repo.add("comment", 1, content="hello")
    repo.store(cached, "hi", content=("hello", "नमस्ते"))
    uncached = repo.add("comment", 2, content="bye")
    uc = make_uc(repo, FakeEngine(configured=False))

    [res] = uc.execute(1, [cached], "hi")
    assert res.status == "ready"
    with pytest.raises(TranslationEngineUnavailableError):
        uc.execute(1, [uncached], "hi")


# ── Endpoint ───────────────────────────────────────────────────────────────────

def _client(pref=None, repo=None):
    from app.core.redis_client import get_redis
    from app.modules.translation.presentation import dependencies as deps
    from app.modules.translation.presentation.router import router

    repo = repo or FakeContentRepo()
    user = CurrentUser(user_id=uuid4(), profile_id=1)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_user_id] = lambda: user.user_id
    app.dependency_overrides[deps.get_resolve_content_language_uc] = (
        lambda: ResolveContentLanguageUseCase(_PrefRepo(pref)))
    app.dependency_overrides[deps.get_translate_content_uc] = lambda: make_uc(repo)
    app.dependency_overrides[get_redis] = lambda: None   # limiter fails open
    return TestClient(app), repo


def test_endpoint_asks_reader_to_choose_when_no_language():
    client, _ = _client(pref=None)
    r = client.post("/translate/content", json={"items": [{"type": "post", "id": "1"}]},
                    headers={"X-App-Language": "en"})
    assert r.status_code == 409
    body = r.json()
    assert body["code"] == "language_required" and "hi" in body["supported"]


def test_endpoint_uses_app_language_and_returns_items():
    repo = FakeContentRepo()
    repo.add("post", 1, title="Wheat", caption="Buy")
    client, _ = _client(pref="mr", repo=repo)
    r = client.post("/translate/content",
                    json={"items": [{"type": "post", "id": "1"}, {"type": "news", "id": "nope"}]},
                    headers={"X-App-Language": "gu"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["lang"] == "gu"
    assert body["items"][0]["status"] == "ready"
    assert body["items"][0]["fields"]["title"] == "[tr] Wheat"
    assert body["items"][1]["status"] == "not_found"


def test_endpoint_rejects_bad_input():
    client, _ = _client(pref="hi")
    assert client.post("/translate/content", json={"items": []}).status_code == 422
    assert client.post("/translate/content", json={
        "items": [{"type": "post", "id": "1"}], "target_lang": "xx"}).status_code == 422
    assert client.post("/translate/content", json={
        "items": [{"type": "message", "id": "1"}]}).status_code == 422
    assert client.post("/translate/content", json={
        "items": [{"type": "post", "id": str(i)} for i in range(21)]}).status_code == 422


def test_canonical_id_collapses_spellings():
    from app.modules.translation.domain.content import canonical_id
    u = uuid4()
    assert canonical_id("post", " 007 ") == "7"
    assert canonical_id("comment", "12") == "12"
    assert canonical_id("news", str(u).upper()) == str(u)
    assert canonical_id("post", "abc") == "abc"      # left for not_found


def test_same_item_twice_with_different_fields_is_one_item():
    repo = FakeContentRepo()
    repo.add("post", 1, title="t", caption="c")
    lock, clock = FakeLock(), FakeClock()
    refs = [ContentRef("post", "1"), ContentRef("post", "1", fields=("title",))]

    results = make_uc(repo, FakeEngine(), lock, clock).execute(1, refs, "hi")

    assert [r.status for r in results] == ["ready"]
    assert clock.t == 0          # never waited on its own lock
    assert len(lock.acquired) == 1


def test_endpoint_normalizes_ids():
    repo = FakeContentRepo()
    repo.add("post", 7, title="Wheat", caption="Buy")
    client, _ = _client(pref="hi", repo=repo)
    r = client.post("/translate/content",
                    json={"items": [{"type": "post", "id": "007"}, {"type": "post", "id": "7"}]})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1 and items[0]["id"] == "7" and items[0]["status"] == "ready"
