"""Exact, rule-based conversion of a name from a "same-family" Indian script
into Devanagari — no AI.

Bengali, Gurmukhi (Punjabi), Gujarati, Telugu, Kannada and Malayalam all
descend from the same Brahmi family as Devanagari, and Unicode lays each
script's block out in parallel with Devanagari's (ISCII order): the same
sound sits at the same offset in every block. So ગૌરી -> गौरी is a letter-for-
letter swap that keeps the sound exactly — no guessing, nothing to verify.

The few letters that do not line up are handled explicitly below. Anything
that still has no clean Devanagari equivalent makes the whole conversion
fail (None): the name then stays as typed, which is always safe.

Tamil and Urdu are NOT here: Tamil writes k/g, t/d, p/b ... with one letter
each and Urdu usually omits short vowels, so neither converts exactly.

Pure Python, no I/O.
"""
from __future__ import annotations

import unicodedata
from typing import Optional

_DEVANAGARI_BASE = 0x0900

# Script block start per language code.
SAME_FAMILY_BLOCKS: dict[str, int] = {
    "bn": 0x0980,   # Bengali
    "pa": 0x0A00,   # Gurmukhi
    "gu": 0x0A80,   # Gujarati
    "te": 0x0C00,   # Telugu
    "kn": 0x0C80,   # Kannada
    "ml": 0x0D00,   # Malayalam
}

_VIRAMA = "्"

# Letters whose parallel Devanagari code point means something else, or that
# have no single-letter equivalent.
_OVERRIDES: dict[str, str] = {
    # Hindi has no short e / short o: Dravidian short vowels -> long.
    "ె": "े", "ొ": "ो", "ఎ": "ए", "ఒ": "ओ",            # Telugu
    "ೆ": "े", "ೊ": "ो", "ಎ": "ए", "ಒ": "ओ",            # Kannada
    "െ": "े", "ൊ": "ो", "എ": "ए", "ഒ": "ओ",            # Malayalam
    # Malayalam chillu letters (a consonant with no vowel) and dot reph.
    "ൺ": "ण्", "ൻ": "न्", "ർ": "र्", "ൽ": "ल्",
    "ൾ": "ळ्", "ൿ": "क्", "ൎ": "र्",
    "ൗ": "ौ",                                                         # au length mark
    # Bengali khanda ta (a final t with no vowel).
    "ৎ": "त्",
    # Gurmukhi tippi = nasal (anusvara).
    "ੰ": "ं",
}
_GURMUKHI_ADDAK = "ੱ"   # doubles the next consonant: ਸੱਤ -> सत्त
_JOINERS = {"‌", "‍"}   # ZWNJ / ZWJ: rendering hints only


def _devanagari_char(ch: str, block: int) -> Optional[str]:
    if ch in _OVERRIDES:
        return _OVERRIDES[ch]
    cp = ord(ch)
    if not block <= cp < block + 0x80:
        return None
    target = chr(cp - block + _DEVANAGARI_BASE)
    name = unicodedata.name(target, "")
    # Only real letters (Lo) and vowel/nasal/virama marks (Mn, Mc) — never a
    # sign or symbol that merely sits at the same offset (the Gujarati rupee
    # sign lands on a Devanagari spacing dot, an Lm).
    if not name.startswith("DEVANAGARI") or unicodedata.category(target) not in ("Lo", "Mn", "Mc"):
        return None
    return target


def to_devanagari(text: str, lang: str) -> Optional[str]:
    """The name in Devanagari, or None if `lang` is not a same-family script
    or any letter has no exact equivalent."""
    block = SAME_FAMILY_BLOCKS.get(lang)
    if block is None or not text:
        return None
    out: list[str] = []
    double_next = False
    for ch in unicodedata.normalize("NFC", text):
        if ch in _JOINERS:
            continue
        if ch == _GURMUKHI_ADDAK and lang == "pa":
            double_next = True
            continue
        if ch.isspace() or (ch.isascii() and not ch.isalpha()):
            out.append(ch)
            double_next = False
            continue
        dev = _devanagari_char(ch, block)
        if dev is None:
            return None
        if double_next and unicodedata.category(dev[0]) == "Lo":
            out.append(dev[0] + _VIRAMA)          # the consonant, doubled
        double_next = False
        out.append(dev)
    result = " ".join("".join(out).split())
    return _hindi_conventions(result) or None


# Hindi writes a nasal before a consonant as anusvara: गाङ्गुली -> गांगुली,
# पञ्च -> पंच. ङ् and ञ् are used for nothing else in names.
_NASAL_BEFORE_CONSONANT = ("ङ्", "ञ्")
# Whole words whose source-script spelling differs from how Hindi always
# writes them. Kept tiny and explicit — only names too common to leave odd.
_WORD_EXCEPTIONS = {
    "सिंघ": "सिंह",   # Punjabi ਸਿੰਘ: Hindi writes Singh as सिंह
}


def _hindi_conventions(text: str) -> str:
    for nasal in _NASAL_BEFORE_CONSONANT:
        text = text.replace(nasal, "ं")
    return " ".join(_WORD_EXCEPTIONS.get(w, w) for w in text.split())
