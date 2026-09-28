from __future__ import annotations

import json

from app.modules.translation.domain.content import ContentSource, FieldValue
from app.modules.translation.domain.prompt import AssembledPrompt, language_name

# Byte-identical on every call, like chat's STATIC_SYSTEM_INSTRUCTION, so the
# engine's prefix caching applies. Everything per-request goes in user_content.
CONTENT_SYSTEM_INSTRUCTION = (
    "You translate user posts, comments and news on an Indian B2B commodity "
    "trading platform (traders, brokers, exporters) into the reader's language. "
    "Translate the meaning the way a trader writing in that language would put "
    "it, not word by word.\n"
    "Rules:\n"
    "1. Names of people, firms, brands, markets (mandis) and places are NEVER "
    "translated. Write them in the target script so they sound the same — "
    "'Ankul Traders' in Hindi is 'अंकुल ट्रेडर्स', not 'अंकुल व्यापारी'.\n"
    "2. Every number, price, quantity, unit, percentage and date stays exactly "
    "as in the source. Unit words may be written in the target script; values "
    "never change.\n"
    "3. Commodity and trade terms: use the word traders in that language "
    "actually use. Where that is the English word, keep it, written in the "
    "target script.\n"
    "4. Input may be English, Hindi, romanized Hindi, Hinglish or code-mixed. "
    "A field already in the target language is returned unchanged.\n"
    "5. You are given a JSON object keyed by item id; each value is an object "
    "of fields. Return ONLY a JSON object with exactly the same item ids, each "
    "with exactly the same fields and shape: a string stays a string, a list "
    "stays a list of the same length in the same order. Never add, drop, merge "
    "or split items or fields.\n"
    "6. Context, if given, is only for disambiguation. Never translate it or "
    "include it in the output."
)


def assemble_content_prompt(
    *,
    items: list[tuple[ContentSource, dict[str, FieldValue]]],
    target_lang: str,
) -> AssembledPrompt:
    """`items` pairs each source with just the fields still to translate — a
    partly translated item never pays for its fields twice."""
    payload = {src.ref.key: todo for src, todo in items}
    contexts = {src.ref.key: src.context for src, _ in items if src.context}

    parts = [f"Target language: {language_name(target_lang)}."]
    if contexts:
        parts.append("Context per item (do not translate):\n"
                     + json.dumps(contexts, ensure_ascii=False))
    parts.append("Items:\n" + json.dumps(payload, ensure_ascii=False))
    return AssembledPrompt(
        system_instruction=CONTENT_SYSTEM_INSTRUCTION,
        user_content="\n\n".join(parts),
        structured_output=True,
    )
