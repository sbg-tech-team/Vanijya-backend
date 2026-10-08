from __future__ import annotations

import json

from app.modules.translation.domain.prompt import AssembledPrompt

# Byte-identical on every call so the engine's prefix caching applies.
TRANSLITERATION_SYSTEM_INSTRUCTION = (
    "You write people's names from an Indian B2B trading app in Hindi (Devanagari "
    "script) so that they SOUND EXACTLY as the person spells them in English.\n"
    "Rules:\n"
    "1. Transliterate, never translate: keep the sound, not the meaning.\n"
    "2. Follow the spelling given, letter for letter in sound. Never add, drop or "
    "change a vowel — above all the LAST vowel of each word: 'Akshay' is "
    "'अक्षय' and 'Akshaya' is 'अक्षया'; these are different people (the ending can "
    "mark gender). 'Priya' is 'प्रिया', never 'प्रिय'.\n"
    "3. Keep every word, in the same order, one Devanagari word per English word. "
    "Initials are written as Hindi letter names: 'R K Sharma' -> 'आर के शर्मा'.\n"
    "4. Use the standard Hindi spelling of a common name when it matches the "
    "English sound ('Pooja' -> 'पूजा', 'Singh' -> 'सिंह', 'Shree' -> 'श्री').\n"
    "5. alt: if the same English spelling could just as well be a DIFFERENT "
    "Devanagari name — most often a final 'a' that may be long or silent "
    "('Rama' -> 'रामा' or 'राम', 'Krishna' -> 'कृष्णा' or 'कृष्ण') — give that other "
    "spelling as alt; otherwise alt is null.\n"
    "6. confidence is your probability (0 to 1) that a native Hindi reader would "
    "write this person's name exactly this way. Lower it whenever the English "
    "spelling is ambiguous — a final 'a' that may be silent, an 'e' that may be "
    "a short 'a', a name that is not of Indian origin, or a spelling you do not "
    "recognise. Do not report 0.9 or higher unless you are sure.\n"
    "Return ONLY JSON: {id: {\"hi\": <Devanagari name>, \"alt\": <Devanagari or null>, "
    "\"confidence\": <0..1>}} "
    "with exactly the ids given."
)


NAME_SUGGESTIONS_SYSTEM_INSTRUCTION = (
    "A person is typing their own name in an Indian B2B trading app. Suggest how "
    "that SAME name is written in the target language's script — the spellings "
    "people with this name actually use, most common first.\n"
    "Rules:\n"
    "1. Transliterate, never translate: keep the sound exactly.\n"
    "2. Never add, drop or change a vowel — above all the LAST vowel of each "
    "word. 'अक्षय' is 'Akshay', never 'Akshaya'; 'Akshaya' is 'अक्षया', never "
    "'अक्षय'. The one allowed difference: a final unwritten vowel may also be "
    "spelled with 'a' in English, as a separate suggestion after the closest "
    "one ('तथागत' -> 'Tathagat', 'Tathagata').\n"
    "3. Keep every word, in the same order. Give different real spellings "
    "only ('Gauri' / 'Gouri', 'Tathagat'), no inventions.\n"
    "Return ONLY JSON: {\"suggestions\": [<spelling>, ...]} with at most 4 entries."
)


def assemble_name_suggestions_prompt(text: str, target_language_name: str) -> AssembledPrompt:
    return AssembledPrompt(
        system_instruction=NAME_SUGGESTIONS_SYSTEM_INSTRUCTION,
        user_content=f"Target language: {target_language_name}.\nName as typed: {text}",
        structured_output=True,
    )


def assemble_transliteration_prompt(names: dict[str, str]) -> AssembledPrompt:
    """`names`: id -> name as written in English letters."""
    return AssembledPrompt(
        system_instruction=TRANSLITERATION_SYSTEM_INSTRUCTION,
        user_content="Names:\n" + json.dumps(names, ensure_ascii=False),
        structured_output=True,
    )
