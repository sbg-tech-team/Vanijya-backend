"""A person's name in several languages — the `name_i18n` dictionary.

`profile.name` stays exactly what the person typed, in whatever script.
`profile.name_i18n` holds the same name per language:

    {"hi": "तथागत", "en": "Tathagata", "auto": ["en"]}

* The language of the typed name is taken from its script (Devanagari ->
  "hi", English letters -> "en"), not from the app language: a Hindi-app user
  may still type English letters.
* Values the person typed or picked themselves are theirs and are never
  overwritten by generation.
* Values the system generated are listed under "auto", so a later
  owner-confirmation step knows exactly what to ask about.
* A language that is absent simply has no name yet; the typed `name` is shown.

Pure Python, no I/O.
"""
from __future__ import annotations

from typing import Optional

from app.modules.translation.domain.prompt import LANGUAGE_NAMES

AUTO_KEY = "auto"
MAX_NAME_LENGTH = 100

# Script -> the language a name typed in it is taken to be. Devanagari is
# shared by Hindi and Marathi; with Hindi the only non-English app language
# today it reads as Hindi.
_SCRIPT_LANGUAGE: tuple[tuple[tuple[int, int], str], ...] = (
    ((0x0900, 0x097F), "hi"), ((0xA8E0, 0xA8FF), "hi"),
    ((0x0980, 0x09FF), "bn"), ((0x0A00, 0x0A7F), "pa"), ((0x0A80, 0x0AFF), "gu"),
    ((0x0B80, 0x0BFF), "ta"), ((0x0C00, 0x0C7F), "te"), ((0x0C80, 0x0CFF), "kn"),
    ((0x0D00, 0x0D7F), "ml"), ((0x0600, 0x06FF), "ur"),
)


def script_language(text: str) -> Optional[str]:
    """The language a name is written in, from the script most of its letters
    use; None if there are no letters."""
    counts: dict[str, int] = {}
    for ch in text or "":
        if not ch.isalpha():
            continue
        cp = ord(ch)
        lang = "en" if ch.isascii() or 0x00C0 <= cp <= 0x024F else None
        if lang is None:
            for (lo, hi), code in _SCRIPT_LANGUAGE:
                if lo <= cp <= hi:
                    lang = code
                    break
        if lang:
            counts[lang] = counts.get(lang, 0) + 1
    return max(counts, key=counts.get) if counts else None


def clean_owner_names(provided: Optional[dict]) -> dict[str, str]:
    """Validate what a person sent as their own spellings: known language
    codes only, non-empty text within length. Raises ValueError."""
    out: dict[str, str] = {}
    for lang, value in (provided or {}).items():
        if lang not in LANGUAGE_NAMES:
            raise ValueError(f"unsupported language {lang!r}; one of {sorted(LANGUAGE_NAMES)}")
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"name for {lang!r} must be non-empty text")
        value = " ".join(value.split())
        if len(value) > MAX_NAME_LENGTH:
            raise ValueError(f"name for {lang!r} is longer than {MAX_NAME_LENGTH} characters")
        out[lang] = value
    return out


def merge_owner_names(
    name: str,
    provided: Optional[dict[str, str]],
    existing: Optional[dict],
    name_changed: bool,
) -> dict:
    """The name_i18n to store after a create or an edit.

    * The typed name is stored under its own language.
    * Spellings the person sent are stored as theirs (removed from "auto").
    * If the name itself changed, every generated value is dropped — it was
      made from the old name — and generation fills them in again.
    """
    keep = {} if name_changed or not existing else {
        k: v for k, v in existing.items() if k != AUTO_KEY and isinstance(v, str)
    }
    auto = set() if name_changed or not existing else set(existing.get(AUTO_KEY) or [])

    src = script_language(name)
    if src:
        keep[src] = name
        auto.discard(src)
    for lang, value in (provided or {}).items():
        keep[lang] = value
        auto.discard(lang)

    out: dict = dict(keep)
    auto &= set(keep)
    if auto:
        out[AUTO_KEY] = sorted(auto)
    return out


def names_to_generate(name: str, name_i18n: Optional[dict], targets: tuple[str, ...]) -> list[str]:
    """Target languages still missing for this name. A stored entry made from
    an older version of the name (its source-language value no longer equals
    `name`) means everything generated is stale."""
    src = script_language(name)
    current = name_i18n or {}
    stale = src is not None and current.get(src) not in (None, name)
    return [t for t in targets if t != src and (stale or not current.get(t))]


def with_generated(name_i18n: Optional[dict], lang: str, value: str) -> dict:
    """Add a generated value — never over one the person gave themselves."""
    out = dict(name_i18n or {})
    if out.get(lang) and lang not in (out.get(AUTO_KEY) or []):
        return out
    out[lang] = value
    out[AUTO_KEY] = sorted(set(out.get(AUTO_KEY) or []) | {lang})
    return out


def display_name(name: str, name_i18n: Optional[dict], lang: Optional[str]) -> str:
    """What a viewer reading the app in `lang` sees: the name in their
    language if there is one, otherwise the name as its owner typed it."""
    if lang and name_i18n:
        value = name_i18n.get(lang)
        if isinstance(value, str) and value.strip():
            return value
    return name
