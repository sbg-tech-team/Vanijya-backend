# entities.py defines what things ARE in pure Python. No database. No HTTP. Just
# shapes of data the rest of the translation module agrees on.

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID


# ── The message being translated ────────────────────────────────────────────────

@dataclass
class TranslatableMessage:
    """The subset of a chat message translation needs — sourced from chat's own
    messages table, mapped into this module's own shape."""
    id: UUID
    context_type: str  # "dm" | "group"
    context_id: UUID
    sender_id: UUID
    body: Optional[str]


@dataclass
class ContextMessage:
    """One earlier message, used only to resolve local referents (e.g. 'kal',
    'bhav') — not stored or cached on its own."""
    id: UUID
    body: Optional[str]
    sent_at: datetime


# ── Rolling conversation context ─────────────────────────────────────────────────

@dataclass
class ContextSnapshot:
    """What the context store knows about a conversation right now."""
    summary: Optional[str]
    due_for_refresh: bool


# ── Reader preferences ────────────────────────────────────────────────────────────

@dataclass
class ReaderConversationPrefs:
    """Per-reader, per-conversation translation settings. target_lang is None
    when the reader has never overridden anything for this conversation —
    resolution then falls through to the reader's app-wide default, then to
    AUTO_FALLBACK."""
    user_id: UUID
    conversation_id: UUID
    target_lang: Optional[str]
    continuous_enabled: bool


# ── Engine I/O ─────────────────────────────────────────────────────────────────────

@dataclass
class EngineResponse:
    translated_text: str
    # Present only when a summary refresh was requested and honored.
    updated_summary: Optional[str] = None
    # Present only for AUTO_FALLBACK calls — which concrete language the engine
    # actually translated into (en or hi), so callers can report it accurately.
    chosen_target_lang: Optional[str] = None


@dataclass
class TranslationResult:
    """What a translate use case hands back to its caller (chat module)."""
    translated_text: str
    target_lang: str
    used_cache: bool
