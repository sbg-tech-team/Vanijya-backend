# Translation Module — Complete Walkthrough

File-by-file, function-by-function trace of `app/modules/translation/` and every
point where it connects into the rest of the app. Reflects the code as it
actually exists after the CI fix (lazy Gemini client init) — not a proposal.

---

## 1. The pipeline, start to end

Two entry points exist. Both end up in the same shared orchestrator
(`TranslationPipeline`), and both never touch a message the reader sent
themselves — only messages they *received*.

```
SINGLE-TAP (reader explicitly asks to translate one message)
──────────────────────────────────────────────────────────────
  POST /chat/messages/{message_id}/translate
        │
        ▼
  chat/presentation/router.py :: translate_message()
        │  Depends(get_translate_message_uc)
        ▼
  translation/presentation/dependencies.py :: get_translate_message_uc()
        │  builds TranslateMessageUseCase with its dependencies
        ▼
  translation/application/use_cases/translate_message.py
        │  1. repository.get_message(message_id)      -- fetch from chat's own table
        │  2. resolve_target_language.execute(...)      -- priority chain -> lang or AUTO_FALLBACK
        │  3. context_store.get_context(...)            -- rolling summary + due-for-refresh flag
        │  4. translation_cache.get(...)                -- short-circuit on a hit
        │  5. pipeline.run(message, target, context)    -- on a miss
        ▼
  translation/application/pipeline.py :: TranslationPipeline.run()
        │  1. repository.get_preceding_messages(...)    -- only if a summary already exists
        │  2. assemble_prompt(...)                       -- domain/prompt.py, pure function
        │  3. engine.translate(prompt)                   -- Gemini call
        │  4. context_store.save_summary(...)            -- only if due_for_refresh AND returned
        ▼
  translation/data/adapters/gemini_engine.py :: GeminiTranslationEngine.translate()
        │  real network call to Gemini
        ▼
  back up the stack -> TranslationResult -> HTTP 200 response


CONTINUOUS (auto-translate on receive, DM only)
──────────────────────────────────────────────────────────────
  POST /chat/conversations/{conv_id}/messages   (an ordinary send_message call)
        │
        ▼
  chat/presentation/router.py :: send_message()
        │  background_tasks.add_task(_translate_incoming_for_receiver, receiver_id, msg.id)
        │  (this happens *alongside* the existing emit_to_user(..., "new_message", ...) task —
        │   the original message is never delayed waiting on translation)
        ▼
  chat/presentation/router.py :: _translate_incoming_for_receiver()   <- runs after the response is sent
        │  opens its OWN db session (the request's is already closed by now)
        │  builds repo / pipeline / use case by calling the dependency factories directly
        ▼
  translation/application/use_cases/handle_incoming_message.py :: HandleIncomingMessageUseCase.execute()
        │  1. repository.get_message(message_id)
        │  2. bail out if not a DM, or reader has no pref, or continuous is off
        │  3. context_store.get_context(...)
        │  4. pipeline.run(message, pref.target_lang, context)   <- same pipeline as single-tap
        ▼
  (same TranslationPipeline.run() as above)
        ▼
  chat/presentation/router.py :: emit_to_user(receiver_id, "message_translated", {...})
        │  a SEPARATE socket event, sent after "new_message" — never bundled with it


TOGGLE (turning continuous on/off for one conversation)
──────────────────────────────────────────────────────────────
  POST /chat/conversations/{conv_id}/continuous-translation
        ▼
  chat/presentation/router.py :: toggle_continuous_translation()
        ▼
  translation/application/use_cases/toggle_continuous.py :: ToggleContinuousTranslationUseCase.execute()
        │  1. reject if context_type != "dm"
        │  2. if enabling: resolve_target_language.execute(...) ONCE, store the concrete result
        │     (or store None if it resolved to AUTO_FALLBACK — see file notes below)
        ▼
  repository.set_conversation_pref(...)   -- upserts the DB row HandleIncomingMessageUseCase reads later
```

---

## 2. Folder tree

```
app/modules/translation/
├── __init__.py                                  (empty — package marker)
├── domain/                                       ← pure Python, no DB, no SDK, no FastAPI
│   ├── __init__.py
│   ├── value_objects.py                          AUTO_FALLBACK sentinel
│   ├── exceptions.py                              TranslationError and its 3 subclasses
│   ├── entities.py                                every dataclass shape the module agrees on
│   ├── prompt.py                                  the layered-prompt assembler (pure function)
│   └── interfaces/                                the 4 ports (ABCs)
│       ├── __init__.py
│       ├── engine.py                              ITranslationEngine
│       ├── context_store.py                       IContextStore
│       ├── translation_cache.py                    ITranslationCache
│       └── repository.py                           ITranslationRepository
├── application/                                   ← orchestration, depends only on the ports above
│   ├── __init__.py
│   ├── pipeline.py                                TranslationPipeline — shared by both trigger modes
│   └── use_cases/
│       ├── __init__.py
│       ├── resolve_target_language.py             ResolveTargetLanguageUseCase
│       ├── translate_message.py                    TranslateMessageUseCase (single-tap)
│       ├── handle_incoming_message.py              HandleIncomingMessageUseCase (continuous)
│       └── toggle_continuous.py                    ToggleContinuousTranslationUseCase
├── data/                                          ← Postgres + Gemini specifics, implements the ports
│   ├── __init__.py
│   ├── models.py                                  3 SQLAlchemy tables
│   ├── repository.py                              TranslationRepository (implements 2 of the 4 ports)
│   └── adapters/
│       ├── __init__.py
│       ├── gemini_engine.py                       GeminiTranslationEngine (implements ITranslationEngine)
│       └── inmemory_cache.py                       InMemoryTranslationCache (implements ITranslationCache)
└── presentation/                                   ← FastAPI DI wiring only, no router of its own
    ├── __init__.py
    └── dependencies.py                             every get_*_uc() factory function

Connection points outside the module:
app/modules/chat/presentation/router.py             the 2 new endpoints + the send_message hook
app/modules/chat/presentation/schemas.py            the 4 new Pydantic request/response models
alembic/versions/69723a8b6af7_*.py                  the migration that creates the 3 tables
app/core/config.py                                   3 new Settings fields
```

---

## 3. Domain layer — `domain/`

Nothing here imports SQLAlchemy, `google.genai`, or FastAPI. Per this repo's own
convention (see `chat/domain/entities.py`'s own header comment), this layer must
run with nothing installed but Python itself.

### 3.1 `domain/value_objects.py`

```python
AUTO_FALLBACK = "__auto__"
```

One constant. Returned by `ResolveTargetLanguageUseCase` when nothing resolves
anywhere — no explicit override, no per-conversation pref, no reader default.
It is never a real language code; it's a signal that `assemble_prompt()` reads
to swap in a completely different instruction (detect the source language,
translate to Hindi if it's already English, otherwise English) instead of
"translate into X." Every other file that cares about this sentinel imports it
from here — there is exactly one definition.

### 3.2 `domain/exceptions.py`

```python
class TranslationError(Exception):
    """Base class for translation module errors."""

class MessageNotFoundError(TranslationError):
    pass

class ContinuousNotAllowedError(TranslationError):
    """Raised when continuous mode is requested for a group — DMs only."""
    pass

class TranslationEngineUnavailableError(TranslationError):
    """The engine has no API key configured. -> 503, never a raw 500."""
    pass
```

Three concrete exceptions, all inheriting `TranslationError`:
- **`MessageNotFoundError`** — raised by `TranslateMessageUseCase` when the
  target message doesn't exist, was deleted, or has no text body. Chat's
  router imports this under the alias `TranslationMessageNotFoundError` (see
  §7) specifically to avoid colliding with chat's *own*
  `MessageNotFoundError` — both classes share a name but live in different
  modules, and importing both under the same bare name in one file would let
  the second import silently shadow the first. That shadowing is exactly the
  bug the CI-driven fix caught and corrected.
- **`ContinuousNotAllowedError`** — raised by `ToggleContinuousTranslationUseCase`
  if `context_type != "dm"`.
- **`TranslationEngineUnavailableError`** — added after the CI failure. Raised
  by `GeminiTranslationEngine._get_client()` when no API key is configured.
  This is the exception that must never be raised at import time (see §5.3).

### 3.3 `domain/entities.py`

Every dataclass the module passes between layers. No behavior, just shape.

```python
@dataclass
class TranslatableMessage:
    id: UUID
    context_type: str          # "dm" | "group"
    context_id: UUID
    sender_id: UUID
    body: Optional[str]
```
The module's own view of a chat message — deliberately not chat's
`MessageEntity` (which carries sender profile info, attachments, receipt
ticks — none of which translation needs). `TranslationRepository.get_message()`
maps chat's SQLAlchemy `Message` row into this shape.

```python
@dataclass
class ContextMessage:
    id: UUID
    body: Optional[str]
    sent_at: datetime
```
One earlier message, used only inside a single `TranslationPipeline.run()` call
to help Gemini resolve local referents ("kal", "bhav"). Never cached or stored
on its own.

```python
@dataclass
class ContextSnapshot:
    summary: Optional[str]
    due_for_refresh: bool
```
What `IContextStore.get_context()` hands back — the current rolling summary
(`None` on a cold start) plus a pre-computed boolean telling the caller whether
*this* call should also ask the engine for an updated summary. The boolean is
computed once, inside the repository, from the K-message-count/TTL check — no
other file re-derives it.

```python
@dataclass
class ReaderConversationPrefs:
    user_id: UUID
    conversation_id: UUID
    target_lang: Optional[str]
    continuous_enabled: bool
```
One reader's settings for one conversation. `target_lang: None` specifically
means "this reader never overrode anything here" — resolution falls through to
their app-wide default, then to `AUTO_FALLBACK`. This is the entity both
`ToggleContinuousTranslationUseCase` writes and `HandleIncomingMessageUseCase`
reads.

```python
@dataclass
class EngineResponse:
    translated_text: str
    updated_summary: Optional[str] = None
    chosen_target_lang: Optional[str] = None
```
What *any* engine implementation returns from `.translate()`. `updated_summary`
is only ever non-`None` when the prompt asked for a refresh (see §3.4).
`chosen_target_lang` is only ever non-`None` on an `AUTO_FALLBACK` call — it's
how Gemini reports back which of `en`/`hi` it actually picked, since nothing
else in the system knows that until the response comes back.

```python
@dataclass
class TranslationResult:
    translated_text: str
    target_lang: str
    used_cache: bool
```
The outward-facing result both use cases hand back to chat. Note this is a
*different* shape from `EngineResponse` — `TranslationResult.target_lang` is
always a concrete code (never `AUTO_FALLBACK`, never `None`); each use case is
responsible for resolving that before constructing this object.

### 3.4 `domain/prompt.py` — the layered prompt, pure logic

This is the file the whole caching design in the original brief hinges on, so
it's worth reading in full.

```python
STATIC_SYSTEM_INSTRUCTION = (
    "You are a translation engine embedded in a B2B freight and commodity trading "
    "chat platform (traders, shippers, exporters). Maintain a professional-colloquial "
    "register — natural for trade conversations, not overly formal. Input may be "
    "romanized Indic text, Hinglish, or code-mixed script; translate the intended "
    "meaning directly in one step, never transliterate first. You may be given a "
    "conversation summary and/or earlier messages as context — use them only to "
    "disambiguate ambiguous terms (prices, dates, commodities, quantities); never "
    "translate or repeat that context in your output."
)
```
This string is **passed unchanged, byte-for-byte, on every single call this
module ever makes** — regardless of target language, regardless of whether a
summary refresh is happening. That's deliberate: it's what lets Gemini's own
prefix caching apply to it. If target language or any conditional instruction
leaked into this constant, every call would have a different prefix and the
caching benefit would disappear. This exact invariant is what
`test_handle_incoming_translates_when_continuous_enabled_using_stored_target`
in `tests/test_translation.py` asserts.

```python
_LANGUAGE_NAMES = {
    "en": "English", "hi": "Hindi (Devanagari script)", "gu": "Gujarati",
    "mr": "Marathi", "ta": "Tamil", "te": "Telugu", "kn": "Kannada",
    "bn": "Bengali", "pa": "Punjabi (Gurmukhi script)", "ml": "Malayalam", "ur": "Urdu",
}

def _language_name(code: str) -> str:
    return _LANGUAGE_NAMES.get(code, code)
```
ISO code → human-readable name, used only to phrase the instruction Gemini
sees ("translate into Gujarati" reads better than "translate into gu," and the
script hint on Hindi/Punjabi disambiguates which script to use). Falls back to
echoing the raw code for anything not in this map — not a validator, just a
display convenience.

```python
@dataclass
class AssembledPrompt:
    system_instruction: str
    user_content: str
    structured_output: bool
```
The fully-built, engine-agnostic prompt. `system_instruction` is always
`STATIC_SYSTEM_INSTRUCTION` verbatim. `structured_output` tells the *adapter*
(not this file) whether to request JSON back.

```python
def assemble_prompt(
    *,
    summary: Optional[str],
    context_messages: list[ContextMessage],
    message_text: str,
    target_lang: Optional[str],
    request_summary_update: bool,
) -> AssembledPrompt:
    is_auto_fallback = target_lang is None
    structured = request_summary_update or is_auto_fallback

    parts: list[str] = []

    if summary:
        parts.append(f"Conversation context so far: {summary}")
    for m in context_messages:
        if m.body:
            parts.append(f"Earlier message: {m.body}")

    if is_auto_fallback:
        parts.append(
            "No target language is set for this reader. Detect the language of the "
            "message below. If it is already English, translate it into Hindi "
            "(Devanagari script); otherwise translate it into English. Report which "
            "language you translated into as chosen_target_lang (ISO 639-1 code)."
        )
    else:
        instruction = f"Translate the following message into {_language_name(target_lang)}."
        if not structured:
            instruction += " Respond with only the translated text, nothing else."
        parts.append(instruction)

    if request_summary_update:
        parts.append(
            "Additionally, produce an updated rolling summary of this conversation for "
            "future translation context: fold the message and any earlier messages "
            "above into the existing conversation context so far. Keep it concise "
            "(2-4 sentences). Report it as updated_summary."
        )

    parts.append(f"Message to translate: {message_text}")

    return AssembledPrompt(
        system_instruction=STATIC_SYSTEM_INSTRUCTION,
        user_content="\n\n".join(parts),
        structured_output=structured,
    )
```

Walking through exactly what this builds, in order:

1. **`target_lang is None` is how `AUTO_FALLBACK` arrives at this layer.**
   Every caller (`TranslateMessageUseCase`, `HandleIncomingMessageUseCase`)
   converts the `AUTO_FALLBACK` string sentinel to a bare `None` before
   calling this function — this file never imports `value_objects.py` at all.
2. **`structured` is true whenever EITHER a summary refresh is due OR the
   target is unknown.** This single boolean is what the adapter (§5.1) uses
   to decide between a cheap bare-text call and a JSON-schema call.
3. **Cold start falls out for free.** If `context_messages` is `[]` (which
   happens whenever `summary is None` — see `TranslationPipeline.run()` in
   §4.1) and `summary` is falsy, the first two `if` blocks simply add
   nothing. There's no separate "cold start" branch anywhere in this file —
   it's the natural zero-message case of the general loop.
4. **The target-language instruction is the ONLY place a concrete language
   ever appears in the prompt** — and it's in the *variable* part
   (`user_content`), never the static part. This is what keeps
   `STATIC_SYSTEM_INSTRUCTION` identical across every language.
5. **The "respond with only the translated text" instruction is
   conditional** (`if not structured`) — it's dropped entirely when JSON
   output is being requested, since the response schema itself constrains
   the shape at the API level; adding a contradictory prose instruction
   ("only the translation" while also asking for `updated_summary`) would be
   actively wrong.
6. **The summary-update instruction is appended independently of the
   auto-fallback instruction** — both can be present in the same prompt
   (e.g. AUTO_FALLBACK *and* a refresh due on the same call), and they don't
   interfere with each other since they're just two more lines in the same
   joined string.

### 3.5 `domain/interfaces/` — the four ports

Four small `ABC`s, each with 1–2 abstract methods. This is the seam CLAUDE.md's
original brief asked for explicitly ("Put both ephemeral stores behind small
interfaces... Tests use in-memory stubs").

**`engine.py`**
```python
class ITranslationEngine(ABC):
    @abstractmethod
    def translate(self, prompt: AssembledPrompt) -> EngineResponse: ...
```
One method. `GeminiTranslationEngine` is the only implementation today;
Sarvam Mayura (named in the original brief as a fallback) would be a second.

**`context_store.py`**
```python
class IContextStore(ABC):
    @abstractmethod
    def get_context(self, context_type: str, context_id: UUID) -> ContextSnapshot: ...
    @abstractmethod
    def save_summary(self, context_type, context_id, summary, last_message_id) -> None: ...
```
Note the docstring's warning: `get_context()` has a side effect (it advances a
counter in the real implementation) — call it once per translate request, not
speculatively. `TranslationRepository` is the only implementation.

**`translation_cache.py`**
```python
class ITranslationCache(ABC):
    @abstractmethod
    def get(self, text: str, target_lang: str, context_fingerprint: str) -> Optional[str]: ...
    @abstractmethod
    def set(self, text: str, target_lang: str, context_fingerprint: str, translated_text: str) -> None: ...
```
`context_fingerprint` (the current summary, or `""`) is part of the key on
both methods — this is what makes it safe to cache a context-dependent
translation at all: change the conversation's summary and the cache key
changes with it, so a stale/wrong-context translation can never be served.
`InMemoryTranslationCache` is the only implementation; a Postgres-backed one
was deliberately *not* built (see §9 — CLAUDE.md's original design point on
replica count never came up because the answer was "one replica").

**`repository.py`**
```python
class ITranslationRepository(ABC):
    @abstractmethod
    def get_message(self, message_id: UUID) -> Optional[TranslatableMessage]: ...
    @abstractmethod
    def get_preceding_messages(self, context_type, context_id, before_message_id, limit) -> list[ContextMessage]: ...
    @abstractmethod
    def get_conversation_pref(self, user_id, conversation_id) -> Optional[ReaderConversationPrefs]: ...
    @abstractmethod
    def get_default_target_lang(self, user_id) -> Optional[str]: ...
    @abstractmethod
    def set_conversation_pref(self, user_id, conversation_id, target_lang=None, continuous_enabled=None) -> ReaderConversationPrefs: ...
    @abstractmethod
    def set_default_target_lang(self, user_id, target_lang) -> None: ...
```
Bundles message-history reads and reader-preference reads/writes into one
interface — matching chat's own `IChatRepository`, which similarly bundles
everything Postgres-related into one class rather than one-interface-per-table.
`TranslationRepository` is the only implementation.

---

## 4. Application layer — `application/`

Depends only on the four ports above — never imports SQLAlchemy or
`google.genai` directly.

### 4.1 `application/pipeline.py` — `TranslationPipeline`

```python
class TranslationPipeline:
    def __init__(self, repository: ITranslationRepository, context_store: IContextStore, engine: ITranslationEngine):
        self.repository = repository
        self.context_store = context_store
        self.engine = engine

    def run(self, message: TranslatableMessage, target_lang: Optional[str], context: ContextSnapshot) -> EngineResponse:
        recent = []
        if context.summary is not None:
            recent = self.repository.get_preceding_messages(
                message.context_type, message.context_id, message.id, limit=2
            )

        prompt = assemble_prompt(
            summary=context.summary,
            context_messages=recent,
            message_text=message.body,
            target_lang=target_lang,
            request_summary_update=context.due_for_refresh,
        )
        response = self.engine.translate(prompt)

        if context.due_for_refresh and response.updated_summary:
            self.context_store.save_summary(
                message.context_type, message.context_id, response.updated_summary, message.id
            )

        return response
```

This is the one piece both trigger modes share, and it takes `context` as a
parameter rather than fetching it itself — deliberately. Both callers
(`TranslateMessageUseCase` and `HandleIncomingMessageUseCase`) need the
`ContextSnapshot` for their *own* purposes before calling `run()` (the cache
fingerprint in one case, nothing extra in the other) — if `run()` fetched it
again internally, `IContextStore.get_context()`'s counter-advancing side
effect would fire twice per request, corrupting the K-message count.

Line by line:
- `if context.summary is not None:` — this single condition is the entire
  cold-start/warm-start branch. Cold start (`summary is None`) means
  `recent` stays `[]`, and `assemble_prompt` naturally produces a
  context-free prompt (see §3.4 point 3).
- `limit=2` — hardcoded. This is the "current + last 2 messages" decision:
  the fixed window replaces what was originally a variable "everything since
  the last summary checkpoint" design: simpler, bounded cost, at the
  accepted cost of a possible gap in the summary if K/TTL triggers a refresh
  after a long quiet stretch.
- `if context.due_for_refresh and response.updated_summary:` — **both**
  conditions matter. `due_for_refresh` alone isn't enough to write, because
  the engine might not have returned a summary at all (a plain/non-structured
  call never asks for one) — this check is what prevents accidentally
  overwriting a real summary with `None`.

### 4.2 `application/use_cases/resolve_target_language.py`

```python
class ResolveTargetLanguageUseCase:
    def __init__(self, repository: ITranslationRepository):
        self.repository = repository

    def execute(self, reader_id: UUID, conversation_id: UUID, explicit_target_lang: Optional[str] = None) -> str:
        if explicit_target_lang:
            return explicit_target_lang

        conv_pref = self.repository.get_conversation_pref(reader_id, conversation_id)
        if conv_pref and conv_pref.target_lang:
            return conv_pref.target_lang

        default = self.repository.get_default_target_lang(reader_id)
        if default:
            return default

        return AUTO_FALLBACK
```
Four `if`/`return` statements, each one rung of the priority chain. Note it
always returns a `str` — either a real code or the `AUTO_FALLBACK` sentinel,
never `None` — callers are responsible for converting the sentinel to `None`
before it reaches `assemble_prompt`.

### 4.3 `application/use_cases/translate_message.py` — single-tap

```python
class TranslateMessageUseCase:
    def __init__(self, repository, context_store, translation_cache, pipeline, resolve_target_language):
        ...  # stores all five

    def execute(self, reader_id: UUID, message_id: UUID, explicit_target_lang: Optional[str] = None) -> TranslationResult:
        message = self.repository.get_message(message_id)
        if message is None or not message.body:
            raise MessageNotFoundError("Message not found or has no text body.")

        target = self.resolve_target_language.execute(reader_id, message.context_id, explicit_target_lang)
        context = self.context_store.get_context(message.context_type, message.context_id)

        cache_key_lang = target if target != AUTO_FALLBACK else AUTO_FALLBACK
        fingerprint = context.summary or ""
        cached = self.translation_cache.get(message.body, cache_key_lang, fingerprint)
        if cached is not None:
            return TranslationResult(translated_text=cached, target_lang=target, used_cache=True)

        engine_target = None if target == AUTO_FALLBACK else target
        response = self.pipeline.run(message, engine_target, context)

        resolved_target = target if target != AUTO_FALLBACK else (response.chosen_target_lang or "en")
        self.translation_cache.set(message.body, cache_key_lang, fingerprint, response.translated_text)

        return TranslationResult(translated_text=response.translated_text, target_lang=resolved_target, used_cache=False)
```

Step by step:
1. **Guard clause first.** No message, or a message with an empty/`None`
   body (e.g. a pure media message), raises immediately — nothing downstream
   ever sees a `None` body.
2. **`context.get_context()` is called exactly once here**, before the cache
   check — this is intentional: the K-message counter advances on *every*
   translate attempt, cache hit or not, because a cache hit still represents
   real translation activity for that conversation.
3. **`cache_key_lang = target if target != AUTO_FALLBACK else AUTO_FALLBACK`**
   — this line is a no-op as written (both branches produce the same value)
   but documents the intent: the cache key uses the literal sentinel string
   when nothing resolved, rather than trying to guess a language before
   knowing what the engine will pick. Two different AUTO_FALLBACK requests
   for the same text+context always hit or miss together, regardless of
   what language either one eventually resolves to.
4. **On a cache hit**, `pipeline.run()` — and therefore the engine — is never
   called. `used_cache=True` is the only signal callers get that no fresh
   API call happened.
5. **`engine_target = None if target == AUTO_FALLBACK else target`** — the
   conversion point mentioned in §4.2: from here down, `None` is the only
   representation of "unresolved" that any downstream code understands.
6. **`resolved_target`** — after the engine call, if the original resolution
   was `AUTO_FALLBACK`, the *actual* answer comes from
   `response.chosen_target_lang`. The `or "en"` fallback exists only for the
   theoretical case where a structured response somehow omits that field
   (schema-enforced, so practically never, but not something to let crash a
   response object construction).
7. **Cache is written unconditionally on a miss** — even for an
   `AUTO_FALLBACK` result, keyed under the literal `AUTO_FALLBACK` string
   (not under whatever language it turned out to be), consistent with point 3.

### 4.4 `application/use_cases/handle_incoming_message.py` — continuous

```python
class HandleIncomingMessageUseCase:
    def __init__(self, repository, context_store, pipeline):
        ...

    def execute(self, receiver_id: UUID, message_id: UUID) -> Optional[TranslationResult]:
        message = self.repository.get_message(message_id)
        if message is None or not message.body or message.context_type != "dm":
            return None

        pref = self.repository.get_conversation_pref(receiver_id, message.context_id)
        if pref is None or not pref.continuous_enabled:
            return None

        context = self.context_store.get_context(message.context_type, message.context_id)
        response = self.pipeline.run(message, pref.target_lang, context)

        resolved_target = pref.target_lang or response.chosen_target_lang or "en"
        return TranslationResult(translated_text=response.translated_text, target_lang=resolved_target, used_cache=False)
```

Three things that differ from single-tap, all deliberate:
1. **`message.context_type != "dm"` is checked right in the first guard
   clause** — this single line is the entire enforcement of "continuous
   never applies to groups." There is no other gate anywhere else in the
   system; if this line were ever removed, group messages would silently
   start being translated continuously.
2. **No `resolve_target_language` call here at all.** `pref.target_lang` is
   read directly and handed straight to `pipeline.run()` — by design, this
   use case never re-runs the resolution chain per message (see
   `ToggleContinuousTranslationUseCase` in §4.5 for where that resolution
   actually happened, once, at opt-in time).
3. **No caching.** Every incoming message is new text by definition, so a
   cache would essentially never hit — `translation_cache` isn't even a
   constructor parameter here.
4. **Returns `Optional[TranslationResult]`**, not a `TranslationResult`
   unconditionally — `None` is a legitimate, expected result (nothing to do),
   and the caller (`_translate_incoming_for_receiver` in chat's router, §7)
   checks for it explicitly before emitting anything.

### 4.5 `application/use_cases/toggle_continuous.py`

```python
class ToggleContinuousTranslationUseCase:
    def __init__(self, repository, resolve_target_language):
        ...

    def execute(self, user_id, conversation_id, context_type, enabled, explicit_target_lang=None) -> ReaderConversationPrefs:
        if context_type != "dm":
            raise ContinuousNotAllowedError("Continuous translation is only available for direct messages.")

        target_to_store = None
        if enabled:
            resolved = self.resolve_target_language.execute(user_id, conversation_id, explicit_target_lang)
            target_to_store = None if resolved == AUTO_FALLBACK else resolved

        return self.repository.set_conversation_pref(
            user_id, conversation_id, target_lang=target_to_store, continuous_enabled=enabled
        )
```

- **The group rejection happens here, not in the router** — `context_type` is
  passed in as a parameter rather than looked up, and the router
  (§7) always passes the literal string `"dm"` for this specific endpoint, so
  in practice this `raise` is currently unreachable dead code from that one
  call site — it exists as a guard for the use case's own contract, not
  because the router can currently trigger it.
- **`target_to_store` starts as `None` and only changes if `enabled` is
  true.** This means calling with `enabled=False` always passes
  `target_lang=None` down to `set_conversation_pref` — which, per that
  method's own implementation (§6.2), means "don't touch the stored
  language." Turning continuous off never erases what language was
  previously set.
- **`resolved == AUTO_FALLBACK` collapses to storing `None`.** This is the
  one case where resolution *does* happen once, up front, but the result
  can't always be stored concretely — if literally nothing resolves (no
  override, no pref, no default), there's no concrete language to save, so
  the stored pref stays `target_lang=None`, and `HandleIncomingMessageUseCase`
  will pass that `None` straight to `pipeline.run()` on every future
  message — meaning `AUTO_FALLBACK` behavior effectively re-runs per-message
  for as long as the reader never sets anything concrete. This is
  intentional: unlike a real language code, "auto-detect" isn't a snapshot-able
  decision — it depends on each future message's own source language.

---

## 5. Data layer — `data/`

Where SQLAlchemy and `google.genai` actually get imported.

### 5.1 `data/adapters/gemini_engine.py` — `GeminiTranslationEngine`

```python
class _StructuredOutput(BaseModel):
    translated_text: str
    updated_summary: Optional[str] = None
    chosen_target_lang: Optional[str] = None
```
A Pydantic model mirroring `EngineResponse`'s three fields, used only as the
`response_schema` passed to Gemini for structured calls — this is what makes
the JSON response reliably parseable rather than free text with delimiters.

```python
class GeminiTranslationEngine(ITranslationEngine):
    def __init__(self, api_key: Optional[str], model: str):
        self._api_key = api_key
        self._model = model
        self._client: Optional[genai.Client] = None

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> genai.Client:
        if self._client is None:
            if not self.is_configured:
                raise TranslationEngineUnavailableError("Gemini API key is not configured")
            self._client = genai.Client(api_key=self._api_key)
        return self._client
```
**This is the exact code that changed to fix the CI crash.** The original
version built `genai.Client(api_key=api_key)` directly inside `__init__`.
`genai.Client(...)` raises `ValueError` immediately if `api_key` is falsy —
and since `presentation/dependencies.py` (§6) constructs this class as a
*module-level singleton* the moment the module is imported, that `ValueError`
fired the instant anything imported the chat router, in any environment
without `GEMINI_API_KEY` set. CI has no such key, so `from app.routers import
register_routers` — needed by nearly every test that spins up the app —
crashed outright.

The fix: `__init__` now only stores the two strings and sets `self._client =
None`. `_get_client()` is a lazy accessor — it only ever constructs the real
`genai.Client` the first time `.translate()` is actually called, and only
raises `TranslationEngineUnavailableError` (a typed, catchable exception, not
a bare `ValueError` from a third-party SDK) at that point, if the key still
isn't set. Once built, the client is cached on `self._client` and reused —
this class is still a long-lived singleton, so construction cost is paid at
most once per process, just not at import time. This mirrors
`StreamVideoProvider` in the calling module (`app/modules/calling/data/adapters/stream_video.py`),
which reads its own key via `getattr(settings, "STREAM_API_KEY", None)`
specifically so an absent key degrades to "not configured" rather than
crashing.

```python
    def translate(self, prompt: AssembledPrompt) -> EngineResponse:
        client = self._get_client()

        if prompt.structured_output:
            config = types.GenerateContentConfig(
                system_instruction=prompt.system_instruction,
                response_mime_type="application/json",
                response_schema=_StructuredOutput,
            )
        else:
            config = types.GenerateContentConfig(system_instruction=prompt.system_instruction)

        response = client.models.generate_content(
            model=self._model,
            contents=prompt.user_content,
            config=config,
        )

        if prompt.structured_output:
            parsed = _StructuredOutput.model_validate_json(response.text)
            return EngineResponse(
                translated_text=parsed.translated_text,
                updated_summary=parsed.updated_summary,
                chosen_target_lang=parsed.chosen_target_lang,
            )
        return EngineResponse(translated_text=response.text.strip())
```
- `client = self._get_client()` is the very first line — this is the only
  place the lazy-construction/unavailable-check actually fires.
- `prompt.structured_output` decides the whole shape of the call: with it
  true, `response_mime_type="application/json"` + `response_schema=_StructuredOutput`
  tell Gemini's API itself to constrain output to that JSON shape — no manual
  parsing tricks, no delimiter conventions.
  Without it, the config carries only `system_instruction`, and the response
  is read as bare text.
- `prompt.user_content` is passed as `contents` — a single string, not a
  multi-turn `contents` list. This module doesn't use Gemini's own multi-turn
  chat state; every call is stateless from the SDK's point of view, with all
  state (summary, recent turns) managed by this codebase and re-supplied
  fresh on the "variable" side of the prompt each time.
- Verified against `google-genai==1.73.1`'s actual field names
  (`GenerateContentConfig.model_fields` was inspected directly to confirm
  `system_instruction`, `response_mime_type`, and `response_schema` are real
  fields, and that a Pydantic model class is an accepted `response_schema`
  value) and against the live API in an earlier session (four real calls:
  plain translate, summary refresh, and both `AUTO_FALLBACK` directions —
  all returned correct, semantically right results).

### 5.2 `data/adapters/inmemory_cache.py` — `InMemoryTranslationCache`

```python
class InMemoryTranslationCache(ITranslationCache):
    def __init__(self, max_size: int = 2000):
        self._max_size = max_size
        self._store: OrderedDict[str, str] = OrderedDict()
        self._lock = Lock()

    @staticmethod
    def _key(text: str, target_lang: str, context_fingerprint: str) -> str:
        raw = f"{target_lang}|{context_fingerprint}|{text}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, text, target_lang, context_fingerprint) -> Optional[str]:
        key = self._key(text, target_lang, context_fingerprint)
        with self._lock:
            if key not in self._store:
                return None
            self._store.move_to_end(key)
            return self._store[key]

    def set(self, text, target_lang, context_fingerprint, translated_text) -> None:
        key = self._key(text, target_lang, context_fingerprint)
        with self._lock:
            self._store[key] = translated_text
            self._store.move_to_end(key)
            if len(self._store) > self._max_size:
                self._store.popitem(last=False)
```
A hand-rolled LRU using a plain `OrderedDict` (no `cachetools` dependency
added — the original brief suggested it, but this avoids a new pip
dependency for something this small). `move_to_end()` on every read *and*
write keeps recently-used entries at the "young" end; `popitem(last=False)`
evicts the oldest entry once the cache exceeds `max_size`. The `Lock` exists
because FastAPI can serve requests from a thread pool for sync endpoints —
without it, two concurrent requests hitting `set()` on the same key could
interleave a partial write. This entire object lives in one process's memory
and is gone on restart — deliberately never backed by Postgres.

### 5.3 `data/models.py` — the three tables

```python
class ConversationTranslationContext(Base):
    __tablename__ = "conversation_translation_context"
    context_type: Mapped[str] = mapped_column(String(10), primary_key=True)
    context_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_summarized_message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    messages_since_refresh: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=..., onupdate=...)
```
Composite primary key `(context_type, context_id)` — no surrogate id column.
This mirrors chat's own `Message.context_type`/`context_id` pair exactly,
including the *reason*: `context_id` can point at either a `conversations.id`
or a `groups.id` depending on `context_type`, so it deliberately carries no
foreign key of its own (same as `Message.context_id`). Only
`last_summarized_message_id` has a real FK, to `messages.id`, with
`ondelete="SET NULL"` — if that specific message ever gets deleted, the
checkpoint reference is dropped rather than blocking the delete or cascading
into deleting the summary itself.

```python
class ReaderConversationTranslationPref(Base):
    __tablename__ = "reader_conversation_translation_prefs"
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    target_lang: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    continuous_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=..., onupdate=...)
```
Composite PK `(user_id, conversation_id)` — this is what makes the pref
per-reader-per-conversation rather than global. `target_lang` nullable by
design (§4.5's `None` case). `continuous_enabled` defaults `False`. No FK on
`conversation_id` to `conversations.id` — a deliberate choice, since this row
type is written by `ToggleContinuousTranslationUseCase` which only ever
operates on DMs in practice, but the column itself doesn't hard-enforce that
at the DB level (the enforcement is entirely in application code, §4.5).

```python
class ReaderTranslationDefault(Base):
    __tablename__ = "reader_translation_defaults"
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    target_lang: Mapped[str] = mapped_column(String(10), nullable=False)
```
Single-column PK `user_id` — a row only exists once a reader has explicitly
set an app-wide default. `target_lang` is `nullable=False` here (unlike the
per-conversation table) precisely because existence of the row *is* the
signal; there's no reason to store a row with a null default. **No endpoint
currently writes to this table** — `ITranslationRepository.set_default_target_lang()`
exists and `TranslationRepository` implements it, but nothing in
`chat/presentation/router.py` calls it. This is one of the documented gaps
(see the "Not yet available" section of the frontend contract artifact from
this same conversation).

### 5.4 `data/repository.py` — `TranslationRepository`

Implements both `ITranslationRepository` and `IContextStore` in one class —
one Postgres session, matching chat's own one-repository-per-module pattern.

```python
class TranslationRepository(ITranslationRepository, IContextStore):
    def __init__(self, db: Session, refresh_every_n_messages: int, refresh_ttl: timedelta):
        self.db = db
        self._k = refresh_every_n_messages
        self._ttl = refresh_ttl
```
`_k` and `_ttl` are injected, not hardcoded — they come from
`settings.TRANSLATION_SUMMARY_REFRESH_EVERY_N_MESSAGES` and
`settings.TRANSLATION_SUMMARY_REFRESH_TTL_HOURS` via `presentation/dependencies.py`
(§6), so the K/TTL policy is a config value, not buried in this file.

```python
    def get_message(self, message_id: UUID) -> Optional[TranslatableMessage]:
        row = self.db.get(Message, message_id)
        if row is None or row.is_deleted:
            return None
        return TranslatableMessage(id=row.id, context_type=row.context_type,
                                    context_id=row.context_id, sender_id=row.sender_id, body=row.body)
```
Imports `Message` directly from `app.modules.chat.data.models` — a
cross-module read of chat's own SQLAlchemy model. This is the same pattern
chat's own repository already uses to read `groups`/`post`/`profile` models
directly; translation reading chat's table is not a new kind of coupling for
this codebase, just the same pattern applied once more. `row.is_deleted`
check means a soft-deleted message is treated identically to a nonexistent
one — nobody can translate a message that's been deleted.

```python
    def get_preceding_messages(self, context_type, context_id, before_message_id, limit) -> list[ContextMessage]:
        before = self.db.get(Message, before_message_id)
        if before is None:
            return []
        rows = (
            self.db.query(Message)
            .filter(Message.context_type == context_type, Message.context_id == context_id,
                    Message.sent_at < before.sent_at, Message.is_deleted.is_(False))
            .order_by(Message.sent_at.desc())
            .limit(limit)
            .all()
        )
        rows.reverse()
        return [ContextMessage(id=r.id, body=r.body, sent_at=r.sent_at) for r in rows]
```
Fetches strictly *older* messages (`sent_at < before.sent_at`) than the one
being translated, ordered newest-first for the `LIMIT`, then `.reverse()`s
the Python list back to chronological order before returning — so
`ContextMessage` entries always read in the same order they were actually
sent, oldest of the pair first.

```python
    def get_context(self, context_type: str, context_id: UUID) -> ContextSnapshot:
        row = self.db.get(ConversationTranslationContext, (context_type, context_id))
        if row is None:
            return ContextSnapshot(summary=None, due_for_refresh=True)

        row.messages_since_refresh += 1
        self.db.commit()

        age = datetime.now(timezone.utc) - row.updated_at
        due = row.messages_since_refresh >= self._k or age >= self._ttl
        return ContextSnapshot(summary=row.summary, due_for_refresh=due)
```
The three-way "due" check lives entirely in these five lines:
- **No row at all** → `due_for_refresh=True` unconditionally (cold start is
  always "due" — there's nothing to refresh *from*, but a refresh is what
  will create the first summary).
- **Row exists** → the counter increments *first*, unconditionally, on every
  call regardless of whether a refresh ends up happening — this is what
  "counts translate requests since last refresh" means in practice (not raw
  chat volume — there's no hook into `send_message` for that, see the
  module's own docstring comment on this field in `data/models.py`).
- `due = count >= K or age >= TTL` — either condition alone is sufficient.

```python
    def save_summary(self, context_type, context_id, summary, last_message_id) -> None:
        row = self.db.get(ConversationTranslationContext, (context_type, context_id))
        if row is None:
            row = ConversationTranslationContext(context_type=context_type, context_id=context_id)
            self.db.add(row)
        row.summary = summary
        row.last_summarized_message_id = last_message_id
        row.messages_since_refresh = 0
        row.updated_at = datetime.now(timezone.utc)
        self.db.commit()
```
Upsert: creates the row if it's the very first summary for this conversation,
otherwise updates in place. **Resets the counter to `0` and stamps
`updated_at` fresh** — this is what makes the K/TTL check in `get_context()`
correct going forward; if this reset were missing, the very next call would
still see a stale high counter and immediately re-trigger "due."

The remaining four methods (`get_conversation_pref`, `get_default_target_lang`,
`set_conversation_pref`, `set_default_target_lang`) are straightforward
get-or-create-then-conditionally-update patterns — the one detail worth
calling out is in `set_conversation_pref`:
```python
    def set_conversation_pref(self, user_id, conversation_id, target_lang=None, continuous_enabled=None):
        row = self.db.get(ReaderConversationTranslationPref, (user_id, conversation_id))
        if row is None:
            row = ReaderConversationTranslationPref(user_id=user_id, conversation_id=conversation_id)
            self.db.add(row)
        if target_lang is not None:
            row.target_lang = target_lang
        if continuous_enabled is not None:
            row.continuous_enabled = continuous_enabled
        self.db.commit()
        ...
```
Both `if ... is not None` guards mean this method does a **partial update** —
passing `target_lang=None` never overwrites an existing value with `None`; it
means "leave it as it is." This is exactly the mechanic
`ToggleContinuousTranslationUseCase` relies on when disabling continuous mode
without erasing the stored language (§4.5).

---

## 6. Presentation layer — `presentation/dependencies.py`

No router lives in this module (Option A from the design discussion: chat
calls these use cases in-process, no HTTP hop between chat and translation).
This file exists purely to wire dependency injection.

```python
_engine = GeminiTranslationEngine(api_key=settings.GEMINI_API_KEY, model=settings.TRANSLATION_GEMINI_MODEL)
_translation_cache = InMemoryTranslationCache()
```
Two module-level singletons, constructed once when this module is first
imported. **This line is exactly why the CI bug happened** (§5.1) — instantiating
`GeminiTranslationEngine` here, at import time, is unavoidable given the
singleton design (the whole point is that the Gemini client and the LRU cache
persist across every request in the process, not get rebuilt per-request),
so the fix had to happen inside the class itself, not by moving this line.

```python
def get_translation_repo(db: Session = Depends(get_db)) -> TranslationRepository:
    return TranslationRepository(
        db,
        refresh_every_n_messages=settings.TRANSLATION_SUMMARY_REFRESH_EVERY_N_MESSAGES,
        refresh_ttl=timedelta(hours=settings.TRANSLATION_SUMMARY_REFRESH_TTL_HOURS),
    )
```
A new `TranslationRepository` per request (via FastAPI's `Depends(get_db)`,
which itself opens a fresh session per request and closes it after) — unlike
the engine and cache, the repository is *not* a singleton, since it wraps a
per-request DB session.

```python
def get_translation_pipeline(repo: TranslationRepository = Depends(get_translation_repo)) -> TranslationPipeline:
    return TranslationPipeline(repository=repo, context_store=repo, engine=_engine)
```
Note `repository=repo, context_store=repo` — the *same* `TranslationRepository`
instance is passed in twice, once under each port name, because that one
class implements both interfaces (§5.4). `engine=_engine` is the shared
singleton, not request-scoped.

```python
def get_translate_message_uc(repo=Depends(get_translation_repo), pipeline=Depends(get_translation_pipeline),
                              resolve=Depends(get_resolve_target_language_uc)) -> TranslateMessageUseCase:
    return TranslateMessageUseCase(
        repository=repo, context_store=repo, translation_cache=_translation_cache,
        pipeline=pipeline, resolve_target_language=resolve,
    )

def get_handle_incoming_message_uc(repo=Depends(get_translation_repo), pipeline=Depends(get_translation_pipeline)) -> HandleIncomingMessageUseCase:
    return HandleIncomingMessageUseCase(repository=repo, context_store=repo, pipeline=pipeline)

def get_toggle_continuous_uc(repo=Depends(get_translation_repo), resolve=Depends(get_resolve_target_language_uc)) -> ToggleContinuousTranslationUseCase:
    return ToggleContinuousTranslationUseCase(repository=repo, resolve_target_language=resolve)
```
Each factory wires exactly the dependencies its use case's `__init__` declares
— nothing more. A subtlety used deliberately in chat's router (§7): because
`Depends(...)` is just a default *parameter value*, these functions can also
be called as **plain Python functions with explicit arguments** — e.g.
`get_translation_repo(db)` — bypassing FastAPI's injection machinery entirely.
That's exactly what `_translate_incoming_for_receiver` does, since it runs
inside a `BackgroundTask`, completely outside any FastAPI request/dependency
context.

---

## 7. Chat-side connection point — `chat/presentation/router.py`

### 7.1 The imports (top of file)

```python
from app.modules.translation.domain.exceptions import ContinuousNotAllowedError, TranslationEngineUnavailableError
from app.modules.translation.domain.exceptions import MessageNotFoundError as TranslationMessageNotFoundError
from app.modules.translation.presentation.dependencies import (
    get_handle_incoming_message_uc,
    get_toggle_continuous_uc,
    get_translate_message_uc,
    get_translation_pipeline,
    get_translation_repo,
)
```
The `as TranslationMessageNotFoundError` alias on the second line is the exact
fix for the import-shadowing bug mentioned in §3.2 — chat's own
`MessageNotFoundError` is imported later in this same file (from
`chat.domain.exceptions`), and without this alias, that later import would
silently rebind the name and the `except` clause below would never actually
catch translation's exception.

### 7.2 `_translate_incoming_for_receiver()` — the continuous-mode background task

```python
def _translate_incoming_for_receiver(receiver_id: UUID, message_id: UUID) -> None:
    db = SessionLocal()
    try:
        repo = get_translation_repo(db)
        pipeline = get_translation_pipeline(repo)
        uc = get_handle_incoming_message_uc(repo, pipeline)
        try:
            result = uc.execute(receiver_id, message_id)
        except TranslationEngineUnavailableError:
            return
        if result is not None:
            asyncio.run(
                emit_to_user(receiver_id, "message_translated", {
                    "message_id": str(message_id),
                    "translated_text": result.translated_text,
                    "target_lang": result.target_lang,
                })
            )
    finally:
        db.close()
```
- **`db = SessionLocal()`** — a brand-new session, opened directly (not via
  FastAPI's `Depends(get_db)`), because this function runs *after* the HTTP
  response has already been sent, by which point the request's own session
  has been closed. This is the established pattern in this codebase for
  anything a `BackgroundTask` needs a database for.
- **`get_translation_repo(db)` / `get_translation_pipeline(repo)` /
  `get_handle_incoming_message_uc(repo, pipeline)`** — these are the exact
  same functions from §6, called as plain functions with real arguments
  instead of through `Depends(...)`, exactly as described at the end of §6.
- **The inner `try/except TranslationEngineUnavailableError: return`** — if
  the engine has no key configured, there's nothing to notify and no HTTP
  response to attach an error to (this is a background task, not a request),
  so it exits quietly rather than raising into FastAPI's background-task
  error logging on every single incoming message.
- **`asyncio.run(emit_to_user(...))`** — `emit_to_user` (from
  `app.core.realtime`) is an `async def`. This function itself is synchronous
  and runs inside `BackgroundTasks`' own worker thread (no event loop already
  running there), so `asyncio.run()` is the correct way to actually execute
  that coroutine rather than just constructing and discarding it unawaited.
- **`finally: db.close()`** wraps everything, including the early `return`
  inside the nested `try` — a `return` inside a `try` block still runs the
  enclosing `finally` on the way out, so the session is always closed.

### 7.3 The hook into `send_message()`

```python
@router.post("/conversations/{conv_id}/messages", status_code=201)
async def send_message(...):
    msg, receiver_id = uc.execute(...)
    background_tasks.add_task(emit_to_user, receiver_id, "new_message", jsonable_encoder(msg))
    background_tasks.add_task(_translate_incoming_for_receiver, receiver_id, msg.id)
    return msg
```
One line added to an existing endpoint. Both background tasks are scheduled
side by side — `new_message` and the translation attempt run independently,
so a slow or failing translation can never delay the original message
delivery, and the HTTP response to the sender (`return msg`) doesn't wait on
either task.

### 7.4 `translate_message()` — single-tap endpoint

```python
@router.post("/messages/{message_id}/translate", response_model=TranslateMessageResponse)
def translate_message(message_id: UUID, body: TranslateMessageRequest,
                       user_id: UUID = Depends(get_current_user_id),
                       uc=Depends(get_translate_message_uc)):
    try:
        return uc.execute(reader_id=user_id, message_id=message_id, explicit_target_lang=body.target_lang)
    except TranslationMessageNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except TranslationEngineUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
```
`user_id` (from the JWT, via `get_current_user_id`) is what gets passed as
`reader_id` — the caller is always the reader, never specified explicitly by
the client, so there's no way to request a translation "on behalf of" another
user. `response_model=TranslateMessageResponse` means FastAPI validates/serializes
the returned `TranslationResult` dataclass against that Pydantic schema
(via `from_attributes = True`, §8) — this is also what makes the response
shape show up correctly in the generated OpenAPI docs, rather than as an
empty `{}` schema.

### 7.5 `toggle_continuous_translation()` — the toggle endpoint

```python
@router.post("/conversations/{conv_id}/continuous-translation", response_model=ToggleContinuousTranslationResponse)
def toggle_continuous_translation(conv_id: UUID, body: ToggleContinuousTranslationRequest,
                                   user_id: UUID = Depends(get_current_user_id),
                                   uc=Depends(get_toggle_continuous_uc)):
    try:
        return uc.execute(user_id=user_id, conversation_id=conv_id, context_type="dm",
                           enabled=body.enabled, explicit_target_lang=body.target_lang)
    except ContinuousNotAllowedError as e:
        raise HTTPException(status_code=400, detail=str(e))
```
`context_type="dm"` is a **hardcoded literal**, not derived from `conv_id` by
looking anything up — this route only ever exists under
`/conversations/{conv_id}/...` (chat's DM namespace, as opposed to
`/groups/{group_id}/...`), so the caller has already implicitly committed to
"this is a DM" just by hitting this URL. This is also why the
`ContinuousNotAllowedError` branch in §4.5 is unreachable from this
particular call site, as noted there.

---

## 8. Chat-side connection point — `chat/presentation/schemas.py`

```python
class TranslateMessageRequest(BaseModel):
    target_lang: Optional[str] = Field(None, max_length=10)


class TranslateMessageResponse(BaseModel):
    translated_text: str
    target_lang: str
    used_cache: bool

    class Config:
        from_attributes = True


class ToggleContinuousTranslationRequest(BaseModel):
    enabled: bool
    target_lang: Optional[str] = Field(None, max_length=10)


class ToggleContinuousTranslationResponse(BaseModel):
    conversation_id: UUID
    target_lang: Optional[str]
    continuous_enabled: bool

    class Config:
        from_attributes = True
```
The two `Response` models exist specifically so `response_model=` on the
router endpoints (§7.4, §7.5) has a real Pydantic schema to validate against
— without them, the endpoints would still work at runtime (FastAPI can
serialize a plain dataclass via `jsonable_encoder` regardless), but the
generated OpenAPI schema would show an empty response body, which is exactly
what a frontend team's `/docs` page showed before these were added.
`class Config: from_attributes = True` is what allows each Pydantic model to
be constructed directly from a dataclass instance's attributes (`TranslationResult`,
`ReaderConversationPrefs`) rather than requiring a dict — the same pattern
already used elsewhere in this codebase, e.g. `PostDealResponse` in
`app/modules/post/application/schemas.py`. Note `ToggleContinuousTranslationResponse`
deliberately omits `user_id` even though `ReaderConversationPrefs` carries
it — the caller already knows their own id from their own auth token, so
echoing it back would be redundant.

---

## 9. Database migration — `alembic/versions/69723a8b6af7_*.py`

```python
revision: str = "69723a8b6af7"
down_revision: Union[str, None] = "2cd2e752e76c"
```
`down_revision` points at `2cd2e752e76c` — the actual current head of
`origin/main`'s migration chain (this took two attempts to get right: the
migration was originally hand-written against a *stale* local head,
`d1e2f3a4b5c6`, discovered to be 35 commits behind `origin/main` only once a
`git pull` surfaced the real chain and forced a rebase of this file's
`down_revision`).

```python
def upgrade() -> None:
    op.create_table("conversation_translation_context", ...)
    op.create_table("reader_conversation_translation_prefs", ...)
    op.create_table("reader_translation_defaults", ...)

def downgrade() -> None:
    op.drop_table("reader_translation_defaults")
    op.drop_table("reader_conversation_translation_prefs")
    op.drop_table("conversation_translation_context")
```
Purely additive — three `CREATE TABLE`s, nothing else touched, and `downgrade()`
drops them in reverse creation order (respecting the FK from
`conversation_translation_context.last_summarized_message_id` and
`reader_conversation_translation_prefs.user_id`/`reader_translation_defaults.user_id`
to already-existing tables — though since only these three new tables
reference *outward*, not the reverse, strict ordering isn't actually required
here, but it's kept symmetric with `upgrade()` regardless). Applied to the
real dev database in an earlier session — `alembic current` confirms the
live DB is at this revision, and a direct query confirmed all three tables
exist.

---

## 10. Config additions — `app/core/config.py`

```python
TRANSLATION_GEMINI_MODEL: str = "gemini-flash-lite-latest"
TRANSLATION_SUMMARY_REFRESH_EVERY_N_MESSAGES: int = 20
TRANSLATION_SUMMARY_REFRESH_TTL_HOURS: int = 24
```
- **`TRANSLATION_GEMINI_MODEL`** — a floating `-latest` alias, not a pinned
  dated model string. Confirmed working against the live API, but the
  comment directly above it in the file (`"model string must be verified
  against Google's current Gemini model catalog before shipping"`) is still
  an open item — Google can move what this alias resolves to without any
  code change here.
- **`TRANSLATION_SUMMARY_REFRESH_EVERY_N_MESSAGES` (K=20)** and
  **`TRANSLATION_SUMMARY_REFRESH_TTL_HOURS` (24)** — the two thresholds
  `TranslationRepository.get_context()` (§5.4) reads to decide
  `due_for_refresh`. Both are read through `settings.*` in
  `presentation/dependencies.py::get_translation_repo()` (§6), not
  hardcoded anywhere in the module itself — changing either number is a
  one-line config edit, no code change.

Both `GEMINI_API_KEY` (used by `GeminiTranslationEngine`, §5.1) and these
three fields sit in the same `Settings` class as every other module's config
(Stream, Sentry, GNews/Groq) — no separate config file for this module.

---

## 11. Tests — `tests/test_translation.py`

29 tests, all running against fakes (`FakeRepo`, `FakeEngine`) — no live DB,
no live Gemini call needed for any of them:

- **Prompt assembly** (5 tests) — cold start has no context layers, warm
  includes them, `AUTO_FALLBACK` and summary-refresh both force
  `structured_output=True`, the plain path asks for translation only.
- **Resolution chain** (4 tests) — one per rung of the priority order in
  §4.2, each proving the earlier rungs are checked first.
- **Pipeline** (3 tests) — cold start skips the recent-message fetch, a
  summary is saved only when both `due_for_refresh` and a real
  `updated_summary` came back, never saved when not due.
- **Single-tap** (4 tests) — not-found raises, cache hit skips the engine
  entirely, cache miss calls it and populates the cache, `AUTO_FALLBACK`
  correctly reports back whatever the engine chose.
- **Continuous** (3 tests) — no-op for groups, no-op when disabled, and the
  one regression test worth calling out specifically:
  `test_handle_incoming_translates_when_continuous_enabled_using_stored_target`
  asserts `engine.calls[0].system_instruction == STATIC_SYSTEM_INSTRUCTION`
  — i.e. it directly checks that the static block never varies by target
  language, which is the entire caching design's load-bearing assumption
  (§3.4).
- **Toggle** (4 tests) — group rejection, resolved target stored on enable,
  `None` stored when nothing resolves, disabling never clears an existing
  stored target.
- **Gemini engine unavailability** (2 tests) — constructing the engine with
  `api_key=None` never raises, and `.translate()` on it raises
  `TranslationEngineUnavailableError` — this pair is what would have caught
  the CI crash before it ever reached CI, had they existed sooner.
- **HTTP wiring** (4 tests) — against the real `main.app` with dependencies
  overridden (no DB/Gemini touched): the translate endpoint returns the
  result and 404s correctly, 503s when the engine is unavailable, and the
  toggle endpoint always forces `context_type="dm"` regardless of what's
  asked.

---

## 12. What deliberately isn't built

- **No HTTP router inside the translation module itself** — chat calls the
  use cases in-process (§6's closing note). If a second consumer (post
  captions, profile bios) ever needs translation, this is the first thing
  that would change.
- **No GET endpoint** to read current continuous-mode state or target
  language for a conversation — only the toggle (write) exists.
- **No endpoint writes `reader_translation_defaults`** — the table and the
  repository method exist; nothing calls them yet.
- **No Postgres-backed output cache** — only the in-process LRU. This was a
  deliberate simplification once translation *output* was decided to live on
  the reader's device, not in this backend's database at all.
- **`TRANSLATION_GEMINI_MODEL` is an unpinned alias**, not a dated model
  string.
