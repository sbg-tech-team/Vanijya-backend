from __future__ import annotations

import json

from app.modules.translation.domain.content import ContentSource, FieldValue
from app.modules.translation.domain.glossary import glossary_for
from app.modules.translation.domain.prompt import AssembledPrompt, language_name

# Byte-identical on every call, like chat's STATIC_SYSTEM_INSTRUCTION, so the
# engine's prefix caching applies. Everything per-request goes in user_content.
CONTENT_SYSTEM_INSTRUCTION = (
    "You translate user posts, comments and news on an Indian B2B commodity "
    "trading platform (traders, brokers, exporters) into the reader's language. "
    "Translate the meaning the way a trader writing in that language would put "
    "it, not word by word. Input may be English, Hindi, romanized Hindi, "
    "Hinglish or code-mixed; every field must be translated, whatever its "
    "input language.\n"
    "Rules:\n"
    "1. SCRIPT. Write the whole output in the target language's own script. "
    "Latin letters are allowed ONLY for codes and abbreviations that are "
    "always written that way: units (MT, kg, qtl), variety and grade codes "
    "(Pusa 1121, IR-64), agency acronyms (DGFT, MSP, FCI) and 'DM'. Everything "
    "else - including English words, romanized Hindi and names - is written "
    "in the target script. Never mix in letters of any other script.\n"
    "2. NAMES. Names of people, local firms and traders, markets (mandis), "
    "ports, cities, states and countries, and month names, are NOT translated "
    "and NEVER left in English letters: write them in the target script so "
    "they sound the same. Examples: Hindi 'Ankul Traders' -> 'अंकुल ट्रेडर्स' "
    "(not 'अंकुल व्यापारी'), 'Karnal' -> 'करनाल', 'October' -> 'अक्टूबर'; "
    "Gujarati 'Unjha' -> 'ઉંઝા', 'Rajkot' -> 'રાજકોટ'; Marathi 'Indore' -> "
    "'इंदूर'; Punjabi 'Mundra port' -> 'ਮੁੰਦਰਾ ਪੋਰਟ'; Tamil 'India' -> 'இந்தியா', "
    "'Andhra Pradesh' -> 'ஆந்திரப் பிரதேசம்'. Only large companies and brands "
    "normally written in English (HCL Technologies, Robotiq.ai, NLC India) may "
    "stay as written.\n"
    "3. TRADE WORDS. Use the word traders in that language actually use. If "
    "traders commonly use the English word, write that English word in the "
    "target script (Hindi: 'loading' -> 'लोडिंग', 'negotiable' -> 'नेगोशिएबल'); "
    "otherwise translate it ('export ban' -> 'निर्यात प्रतिबंध'). Romanized "
    "Hindi words are translated like any other word ('gehu' -> Gujarati 'ઘઉં'). "
    "Text written in another Indian language (e.g. romanized Gujarati 'maal "
    "saru che') is translated for its meaning; never carry its words over. "
    "When a glossary is given, use its words exactly for those terms.\n"
    "4. NUMBERS. Every number, price, quantity, percentage and date stays "
    "exactly as in the source, in the same digits. Month and unit words may "
    "be written in the target script; values never change. Never turn a word "
    "into a number it only approximates: 'fortnight' stays a word (Marathi "
    "'पंधरवडा'), not '15 days'.\n"
    "5. SHAPE. You are given a JSON object keyed by item id; each value is an "
    "object of fields. Return ONLY a JSON object with exactly the same item "
    "ids, each with exactly the same fields and shape: a string stays a "
    "string, a list stays a list of the same length in the same order. Never "
    "add, drop, merge or split items or fields.\n"
    "6. CONTEXT. Context, if given, is only for disambiguation. Never translate "
    "it or include it in the output."
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

    parts = [f"Target language: {language_name(target_lang)}. Write in this "
             "language itself — its own words and grammar — not in a related "
             "language that shares its script. The rules' examples are Hindi "
             "only to illustrate."]
    if contexts:
        parts.append("Context per item (do not translate):\n"
                     + json.dumps(contexts, ensure_ascii=False))
    # Only the terms that occur in this batch, so the prompt stays short.
    texts = [v if isinstance(v, str) else " ".join(v)
             for _, todo in items for v in todo.values()]
    terms = glossary_for(texts, target_lang)
    if terms:
        parts.append("Glossary (use exactly these words):\n"
                     + "\n".join(f"- {en} -> {word}" for en, word in terms))
    parts.append("Items:\n" + json.dumps(payload, ensure_ascii=False))
    return AssembledPrompt(
        system_instruction=CONTENT_SYSTEM_INSTRUCTION,
        user_content="\n\n".join(parts),
        structured_output=True,
    )
