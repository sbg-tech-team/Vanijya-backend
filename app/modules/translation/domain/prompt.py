from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.modules.translation.domain.entities import ContextMessage

# The ONLY part of the prompt that is byte-identical across every single
# translate call, ever — role + register + how to treat context. Everything
# that varies per request (target language, summary-refresh ask, the message
# itself) lives in the per-request content instead, so this stays maximally
# cacheable by the engine's own prefix caching.
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

_LANGUAGE_NAMES = {
    "en": "English",
    "hi": "Hindi (Devanagari script)",
    "gu": "Gujarati",
    "mr": "Marathi",
    "ta": "Tamil",
    "te": "Telugu",
    "kn": "Kannada",
    "bn": "Bengali",
    "pa": "Punjabi (Gurmukhi script)",
    "ml": "Malayalam",
    "ur": "Urdu",
}


def _language_name(code: str) -> str:
    return _LANGUAGE_NAMES.get(code, code)


@dataclass
class AssembledPrompt:
    system_instruction: str
    user_content: str
    structured_output: bool


def assemble_prompt(
    *,
    summary: Optional[str],
    context_messages: list[ContextMessage],
    message_text: str,
    target_lang: Optional[str],
    request_summary_update: bool,
) -> AssembledPrompt:
    """target_lang=None means AUTO_FALLBACK — no target resolved anywhere, let the
    engine detect the source language and decide en/hi itself."""
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
