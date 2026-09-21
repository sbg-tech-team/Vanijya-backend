"""
tests/test_translation.py

Unit tests for the translation module's domain/application layer. No DB, no
live Gemini call — every port (repository, context store, engine) is a fake
in-memory double, so these run standalone regardless of the current
alembic/DB state.

Run:
    pytest tests/test_translation.py -v
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID, uuid4

import pytest

from app.modules.translation.application.pipeline import TranslationPipeline
from app.modules.translation.application.use_cases.handle_incoming_message import HandleIncomingMessageUseCase
from app.modules.translation.application.use_cases.resolve_target_language import ResolveTargetLanguageUseCase
from app.modules.translation.application.use_cases.toggle_continuous import ToggleContinuousTranslationUseCase
from app.modules.translation.application.use_cases.translate_message import TranslateMessageUseCase
from app.modules.translation.data.adapters.gemini_engine import GeminiTranslationEngine
from app.modules.translation.data.adapters.inmemory_cache import InMemoryTranslationCache
from app.modules.translation.domain.entities import (
    ContextMessage,
    ContextSnapshot,
    EngineResponse,
    ReaderConversationPrefs,
    TranslatableMessage,
)
from app.modules.translation.domain.exceptions import NotAConversationMemberError
from app.modules.translation.domain.exceptions import (
    ContinuousNotAllowedError,
    MessageNotFoundError,
    TranslationEngineUnavailableError,
)
from app.modules.translation.domain.prompt import STATIC_SYSTEM_INSTRUCTION, assemble_prompt
from app.modules.translation.domain.value_objects import AUTO_FALLBACK


# ── Fakes ──────────────────────────────────────────────────────────────────────

@dataclass
class FakeRepo:
    """Implements ITranslationRepository + IContextStore in-memory."""
    messages: dict = field(default_factory=dict)          # id -> TranslatableMessage
    history: dict = field(default_factory=dict)           # (context_type, context_id) -> [ContextMessage]
    conv_prefs: dict = field(default_factory=dict)         # (user_id, conv_id) -> ReaderConversationPrefs
    defaults: dict = field(default_factory=dict)           # user_id -> str
    contexts: dict = field(default_factory=dict)           # (context_type, context_id) -> dict(summary, count, updated_at)
    k: int = 3
    ttl: timedelta = field(default_factory=lambda: timedelta(hours=24))
    save_summary_calls: list = field(default_factory=list)
    saved_translations: dict = field(default_factory=dict)  # (msg_id, lang) -> text
    # (reader_id, context_type, context_id) the reader may read; None = allow all
    memberships: Optional[set] = None

    # message history
    def get_message(self, message_id: UUID) -> Optional[TranslatableMessage]:
        return self.messages.get(message_id)

    def save_translation(self, message_id, target_lang, translated_text) -> None:
        self.saved_translations[(message_id, target_lang)] = translated_text

    def reader_is_member(self, reader_id, context_type, context_id) -> bool:
        if self.memberships is None:
            return True
        return (reader_id, context_type, context_id) in self.memberships

    def get_preceding_messages(self, context_type, context_id, before_message_id, limit):
        return self.history.get((context_type, context_id), [])[-limit:]

    # context store
    def get_context(self, context_type, context_id) -> ContextSnapshot:
        key = (context_type, context_id)
        row = self.contexts.get(key)
        if row is None:
            return ContextSnapshot(summary=None, due_for_refresh=True)
        row["count"] += 1
        age = datetime.now(timezone.utc) - row["updated_at"]
        due = row["count"] >= self.k or age >= self.ttl
        return ContextSnapshot(summary=row["summary"], due_for_refresh=due)

    def save_summary(self, context_type, context_id, summary, last_message_id):
        key = (context_type, context_id)
        self.contexts[key] = {"summary": summary, "count": 0, "updated_at": datetime.now(timezone.utc)}
        self.save_summary_calls.append((context_type, context_id, summary, last_message_id))

    # reader prefs
    def get_conversation_pref(self, user_id, conversation_id) -> Optional[ReaderConversationPrefs]:
        return self.conv_prefs.get((user_id, conversation_id))

    def get_default_target_lang(self, user_id) -> Optional[str]:
        return self.defaults.get(user_id)

    def set_conversation_pref(self, user_id, conversation_id, target_lang=None, continuous_enabled=None):
        key = (user_id, conversation_id)
        existing = self.conv_prefs.get(key)
        new_target = target_lang if target_lang is not None else (existing.target_lang if existing else None)
        new_enabled = continuous_enabled if continuous_enabled is not None else (existing.continuous_enabled if existing else False)
        pref = ReaderConversationPrefs(
            user_id=user_id, conversation_id=conversation_id,
            target_lang=new_target, continuous_enabled=new_enabled,
        )
        self.conv_prefs[key] = pref
        return pref

    def set_default_target_lang(self, user_id, target_lang):
        self.defaults[user_id] = target_lang


@dataclass
class FakeEngine:
    """Returns a canned response and records every prompt it was called with."""
    response: EngineResponse
    calls: list = field(default_factory=list)

    def translate(self, prompt):
        self.calls.append(prompt)
        return self.response


def make_message(context_type="dm", body="hello") -> TranslatableMessage:
    return TranslatableMessage(id=uuid4(), context_type=context_type, context_id=uuid4(), sender_id=uuid4(), body=body)


# ── domain/prompt.py — pure logic ───────────────────────────────────────────────

def test_assemble_prompt_cold_start_has_no_context_layers():
    prompt = assemble_prompt(
        summary=None, context_messages=[], message_text="hi", target_lang="hi", request_summary_update=False,
    )
    assert "Conversation context so far" not in prompt.user_content
    assert "Earlier message" not in prompt.user_content
    assert prompt.structured_output is False


def test_assemble_prompt_warm_includes_summary_and_recent_turns():
    msg = ContextMessage(id=uuid4(), body="bhav kya hai", sent_at=datetime.now(timezone.utc))
    prompt = assemble_prompt(
        summary="Discussing wheat pricing.", context_messages=[msg], message_text="theek hai",
        target_lang="en", request_summary_update=False,
    )
    assert "Discussing wheat pricing." in prompt.user_content
    assert "bhav kya hai" in prompt.user_content


def test_assemble_prompt_auto_fallback_is_structured_and_has_no_named_language():
    prompt = assemble_prompt(
        summary=None, context_messages=[], message_text="thank you", target_lang=None, request_summary_update=False,
    )
    assert prompt.structured_output is True
    assert "Detect the language" in prompt.user_content


def test_assemble_prompt_summary_refresh_forces_structured_output():
    prompt = assemble_prompt(
        summary="Old summary.", context_messages=[], message_text="hi", target_lang="hi", request_summary_update=True,
    )
    assert prompt.structured_output is True
    assert "updated_summary" in prompt.user_content


def test_assemble_prompt_plain_path_asks_for_translation_only():
    prompt = assemble_prompt(
        summary=None, context_messages=[], message_text="hi", target_lang="hi", request_summary_update=False,
    )
    assert "nothing else" in prompt.user_content


# ── ResolveTargetLanguageUseCase — priority chain ───────────────────────────────

def test_resolve_explicit_override_wins_over_everything():
    repo = FakeRepo()
    user_id, conv_id = uuid4(), uuid4()
    repo.conv_prefs[(user_id, conv_id)] = ReaderConversationPrefs(user_id, conv_id, "hi", False)
    repo.defaults[user_id] = "gu"

    result = ResolveTargetLanguageUseCase(repo).execute(user_id, conv_id, explicit_target_lang="ta")
    assert result == "ta"


def test_resolve_falls_back_to_conversation_pref():
    repo = FakeRepo()
    user_id, conv_id = uuid4(), uuid4()
    repo.conv_prefs[(user_id, conv_id)] = ReaderConversationPrefs(user_id, conv_id, "hi", False)
    repo.defaults[user_id] = "gu"

    result = ResolveTargetLanguageUseCase(repo).execute(user_id, conv_id, explicit_target_lang=None)
    assert result == "hi"


def test_resolve_falls_back_to_reader_default():
    repo = FakeRepo()
    user_id, conv_id = uuid4(), uuid4()
    repo.defaults[user_id] = "gu"

    result = ResolveTargetLanguageUseCase(repo).execute(user_id, conv_id, explicit_target_lang=None)
    assert result == "gu"


def test_resolve_falls_back_to_auto_when_nothing_set():
    repo = FakeRepo()
    result = ResolveTargetLanguageUseCase(repo).execute(uuid4(), uuid4(), explicit_target_lang=None)
    assert result == AUTO_FALLBACK


# ── TranslationPipeline ──────────────────────────────────────────────────────────

def test_pipeline_cold_start_skips_recent_message_fetch():
    repo = FakeRepo()
    engine = FakeEngine(response=EngineResponse(translated_text="hola"))
    pipeline = TranslationPipeline(repository=repo, context_store=repo, engine=engine)
    message = make_message()

    context = ContextSnapshot(summary=None, due_for_refresh=True)
    pipeline.run(message, "es", context)

    prompt = engine.calls[0]
    assert "Earlier message" not in prompt.user_content


def test_pipeline_saves_summary_only_when_due_and_returned():
    repo = FakeRepo()
    engine = FakeEngine(response=EngineResponse(translated_text="hola", updated_summary="new summary"))
    pipeline = TranslationPipeline(repository=repo, context_store=repo, engine=engine)
    message = make_message()

    pipeline.run(message, "es", ContextSnapshot(summary="old", due_for_refresh=True))
    assert len(repo.save_summary_calls) == 1
    assert repo.save_summary_calls[0][2] == "new summary"


def test_pipeline_does_not_save_summary_when_not_due():
    repo = FakeRepo()
    engine = FakeEngine(response=EngineResponse(translated_text="hola", updated_summary="new summary"))
    pipeline = TranslationPipeline(repository=repo, context_store=repo, engine=engine)
    message = make_message()

    pipeline.run(message, "es", ContextSnapshot(summary="old", due_for_refresh=False))
    assert repo.save_summary_calls == []


# ── TranslateMessageUseCase (single-tap) ────────────────────────────────────────

def test_translate_message_not_found_raises():
    repo = FakeRepo()
    uc = TranslateMessageUseCase(
        repository=repo, context_store=repo, translation_cache=InMemoryTranslationCache(),
        pipeline=TranslationPipeline(repo, repo, FakeEngine(EngineResponse("x"))),
        resolve_target_language=ResolveTargetLanguageUseCase(repo),
    )
    with pytest.raises(MessageNotFoundError):
        uc.execute(reader_id=uuid4(), message_id=uuid4())


def test_translate_message_refuses_a_non_member():
    """Anyone authenticated can guess a message id; without the membership
    check /translate hands back the plaintext of any DM on the platform."""
    repo = FakeRepo(memberships=set())  # reader is in nothing
    message = make_message(body="namaste")
    repo.messages[message.id] = message
    engine = FakeEngine(response=EngineResponse(translated_text="SHOULD NOT BE USED"))

    uc = TranslateMessageUseCase(
        repository=repo, context_store=repo, translation_cache=InMemoryTranslationCache(),
        pipeline=TranslationPipeline(repo, repo, engine),
        resolve_target_language=ResolveTargetLanguageUseCase(repo),
    )
    with pytest.raises(NotAConversationMemberError):
        uc.execute(reader_id=uuid4(), message_id=message.id, explicit_target_lang="en")
    assert engine.calls == []  # and we never paid Gemini for it


def test_translate_message_allows_a_member():
    repo = FakeRepo()
    message = make_message(body="namaste")
    repo.messages[message.id] = message
    reader = uuid4()
    repo.memberships = {(reader, message.context_type, message.context_id)}
    engine = FakeEngine(response=EngineResponse(translated_text="hello"))

    uc = TranslateMessageUseCase(
        repository=repo, context_store=repo, translation_cache=InMemoryTranslationCache(),
        pipeline=TranslationPipeline(repo, repo, engine),
        resolve_target_language=ResolveTargetLanguageUseCase(repo),
    )
    assert uc.execute(reader_id=reader, message_id=message.id, explicit_target_lang="en").translated_text == "hello"


def test_translate_message_cache_hit_skips_engine_call():
    repo = FakeRepo()
    message = make_message(body="namaste")
    repo.messages[message.id] = message
    cache = InMemoryTranslationCache()
    cache.set("namaste", "en", "", "hello")
    engine = FakeEngine(response=EngineResponse(translated_text="SHOULD NOT BE USED"))

    uc = TranslateMessageUseCase(
        repository=repo, context_store=repo, translation_cache=cache,
        pipeline=TranslationPipeline(repo, repo, engine),
        resolve_target_language=ResolveTargetLanguageUseCase(repo),
    )
    result = uc.execute(reader_id=uuid4(), message_id=message.id, explicit_target_lang="en")

    assert result.used_cache is True
    assert result.translated_text == "hello"
    assert engine.calls == []


def test_translate_message_cache_miss_calls_engine_and_populates_cache():
    repo = FakeRepo()
    message = make_message(body="namaste")
    repo.messages[message.id] = message
    cache = InMemoryTranslationCache()
    engine = FakeEngine(response=EngineResponse(translated_text="hello"))

    uc = TranslateMessageUseCase(
        repository=repo, context_store=repo, translation_cache=cache,
        pipeline=TranslationPipeline(repo, repo, engine),
        resolve_target_language=ResolveTargetLanguageUseCase(repo),
    )
    result = uc.execute(reader_id=uuid4(), message_id=message.id, explicit_target_lang="en")

    assert result.used_cache is False
    assert result.translated_text == "hello"
    assert cache.get("namaste", "en", "") == "hello"


def test_translate_message_auto_fallback_reports_chosen_language():
    repo = FakeRepo()
    message = make_message(body="thanks")
    repo.messages[message.id] = message
    engine = FakeEngine(response=EngineResponse(translated_text="dhanyavaad", chosen_target_lang="hi"))

    uc = TranslateMessageUseCase(
        repository=repo, context_store=repo, translation_cache=InMemoryTranslationCache(),
        pipeline=TranslationPipeline(repo, repo, engine),
        resolve_target_language=ResolveTargetLanguageUseCase(repo),
    )
    result = uc.execute(reader_id=uuid4(), message_id=message.id)  # nothing resolved anywhere -> AUTO_FALLBACK

    assert result.target_lang == "hi"
    assert engine.calls[0].structured_output is True


# ── HandleIncomingMessageUseCase (continuous) ────────────────────────────────────

def test_handle_incoming_returns_none_for_group_messages():
    repo = FakeRepo()
    message = make_message(context_type="group")
    repo.messages[message.id] = message
    uc = HandleIncomingMessageUseCase(repo, repo, TranslationPipeline(repo, repo, FakeEngine(EngineResponse("x"))))

    assert uc.execute(receiver_id=uuid4(), message_id=message.id) is None


def test_handle_incoming_returns_none_when_continuous_disabled():
    repo = FakeRepo()
    message = make_message(context_type="dm")
    repo.messages[message.id] = message
    receiver_id = uuid4()
    repo.conv_prefs[(receiver_id, message.context_id)] = ReaderConversationPrefs(
        receiver_id, message.context_id, "hi", continuous_enabled=False
    )
    uc = HandleIncomingMessageUseCase(repo, repo, TranslationPipeline(repo, repo, FakeEngine(EngineResponse("x"))))

    assert uc.execute(receiver_id, message.id) is None


def test_handle_incoming_translates_when_continuous_enabled_using_stored_target():
    repo = FakeRepo()
    message = make_message(context_type="dm", body="kal milte hain")
    repo.messages[message.id] = message
    receiver_id = uuid4()
    repo.conv_prefs[(receiver_id, message.context_id)] = ReaderConversationPrefs(
        receiver_id, message.context_id, "en", continuous_enabled=True
    )
    engine = FakeEngine(response=EngineResponse(translated_text="see you tomorrow"))
    uc = HandleIncomingMessageUseCase(repo, repo, TranslationPipeline(repo, repo, engine))

    result = uc.execute(receiver_id, message.id)
    assert result.translated_text == "see you tomorrow"
    assert result.target_lang == "en"
    # the static block must stay byte-identical regardless of target language,
    # or the engine's own prefix caching on it breaks
    assert engine.calls[0].system_instruction == STATIC_SYSTEM_INSTRUCTION


# ── ToggleContinuousTranslationUseCase ──────────────────────────────────────────

def test_toggle_continuous_rejects_groups():
    repo = FakeRepo()
    uc = ToggleContinuousTranslationUseCase(repo, ResolveTargetLanguageUseCase(repo))
    with pytest.raises(ContinuousNotAllowedError):
        uc.execute(uuid4(), uuid4(), context_type="group", enabled=True)


def test_toggle_continuous_stores_resolved_target_on_enable():
    repo = FakeRepo()
    user_id, conv_id = uuid4(), uuid4()
    repo.defaults[user_id] = "mr"
    uc = ToggleContinuousTranslationUseCase(repo, ResolveTargetLanguageUseCase(repo))

    pref = uc.execute(user_id, conv_id, context_type="dm", enabled=True)
    assert pref.continuous_enabled is True
    assert pref.target_lang == "mr"


def test_toggle_continuous_stores_none_target_when_nothing_resolves():
    repo = FakeRepo()
    user_id, conv_id = uuid4(), uuid4()
    uc = ToggleContinuousTranslationUseCase(repo, ResolveTargetLanguageUseCase(repo))

    pref = uc.execute(user_id, conv_id, context_type="dm", enabled=True)
    assert pref.continuous_enabled is True
    assert pref.target_lang is None


def test_toggle_continuous_disable_does_not_clear_existing_target():
    repo = FakeRepo()
    user_id, conv_id = uuid4(), uuid4()
    repo.conv_prefs[(user_id, conv_id)] = ReaderConversationPrefs(user_id, conv_id, "ta", continuous_enabled=True)
    uc = ToggleContinuousTranslationUseCase(repo, ResolveTargetLanguageUseCase(repo))

    pref = uc.execute(user_id, conv_id, context_type="dm", enabled=False)
    assert pref.continuous_enabled is False
    assert pref.target_lang == "ta"


# ── GeminiTranslationEngine — must survive a missing API key at import time ────

def test_gemini_engine_construction_never_raises_without_a_key():
    """This is what CI actually hit: presentation/dependencies.py builds this
    as a module-level singleton at import time, so __init__ raising here would
    crash importing the chat router in any environment without the key set."""
    engine = GeminiTranslationEngine(api_key=None, model="gemini-flash-lite-latest")
    assert engine.is_configured is False


def test_gemini_engine_translate_raises_unavailable_without_a_key():
    engine = GeminiTranslationEngine(api_key=None, model="gemini-flash-lite-latest")
    prompt = assemble_prompt(summary=None, context_messages=[], message_text="hi", target_lang="en", request_summary_update=False)
    with pytest.raises(TranslationEngineUnavailableError):
        engine.translate(prompt)


# ── HTTP wiring — chat's new endpoints, dependencies overridden (no DB/Gemini) ──

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.dependencies import get_current_user_id  # noqa: E402
from app.modules.translation.domain.entities import TranslationResult  # noqa: E402
from app.modules.translation.domain.exceptions import MessageNotFoundError as _MsgNotFound  # noqa: E402
from app.modules.translation.presentation.dependencies import (  # noqa: E402
    get_toggle_continuous_uc,
    get_translate_message_uc,
)

_http_app = main.app
_fastapi_app = main.app.other_asgi_app
_MOCK_USER_ID = uuid4()


@pytest.fixture
def http_client():
    _fastapi_app.dependency_overrides[get_current_user_id] = lambda: _MOCK_USER_ID
    with TestClient(_http_app, raise_server_exceptions=False) as c:
        yield c
    _fastapi_app.dependency_overrides.clear()


def test_translate_endpoint_returns_translation(http_client):
    class StubUC:
        def execute(self, reader_id, message_id, explicit_target_lang=None):
            assert reader_id == _MOCK_USER_ID
            return TranslationResult(translated_text="hello", target_lang="en", used_cache=False)

    _fastapi_app.dependency_overrides[get_translate_message_uc] = lambda: StubUC()
    resp = http_client.post(f"/chat/messages/{uuid4()}/translate", json={"target_lang": "en"})
    assert resp.status_code == 200
    assert resp.json() == {"translated_text": "hello", "target_lang": "en", "used_cache": False}


def test_translate_endpoint_404s_on_missing_message(http_client):
    class StubUC:
        def execute(self, reader_id, message_id, explicit_target_lang=None):
            raise _MsgNotFound("Message not found or has no text body.")

    _fastapi_app.dependency_overrides[get_translate_message_uc] = lambda: StubUC()
    resp = http_client.post(f"/chat/messages/{uuid4()}/translate", json={})
    assert resp.status_code == 404


def test_translate_endpoint_503s_when_engine_unconfigured(http_client):
    class StubUC:
        def execute(self, reader_id, message_id, explicit_target_lang=None):
            raise TranslationEngineUnavailableError("Gemini API key is not configured")

    _fastapi_app.dependency_overrides[get_translate_message_uc] = lambda: StubUC()
    resp = http_client.post(f"/chat/messages/{uuid4()}/translate", json={})
    assert resp.status_code == 503


def test_toggle_continuous_endpoint_forces_dm_context_type(http_client):
    class StubUC:
        def execute(self, user_id, conversation_id, context_type, enabled, explicit_target_lang=None):
            assert context_type == "dm"
            return ReaderConversationPrefs(user_id, conversation_id, explicit_target_lang, enabled)

    _fastapi_app.dependency_overrides[get_toggle_continuous_uc] = lambda: StubUC()
    conv_id = uuid4()
    resp = http_client.post(f"/chat/conversations/{conv_id}/continuous-translation", json={"enabled": True, "target_lang": "hi"})
    assert resp.status_code == 200
    assert resp.json()["continuous_enabled"] is True
