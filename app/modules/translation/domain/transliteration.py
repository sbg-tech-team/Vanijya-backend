"""Name transliteration (English letters -> Devanagari) — the confidence check.

A person's name must sound the same in the app language: "Akshay" is अक्षय,
"Akshaya" is अक्षया, and the two must never be swapped (a changed final vowel
can change a name's gender). The engine proposes a spelling; this module
decides, with fixed rules and no AI, whether that spelling can be trusted.

Both sides are reduced to a "sound key":
  * the English name: digraphs folded (sh->s, ph->f, ee->i, aa->a, w->v ...),
    doubled letters collapsed;
  * the Devanagari spelling: each letter mapped to the same alphabet, with
    Hindi's inherent "a" handled the way Hindi pronounces it — dropped at the
    end of a word (अक्षय -> aksay), optional in the middle (कमला matches both
    "Kamala" and "Kamla").
The keys must match. The END of each word is strict: an extra or missing final
vowel fails. Anything the rules cannot reconcile fails too — a failure means
the original English name is shown, which is always safe.

Pure Python, no I/O.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

STATUS_CONFIDENT = "confident"    # shown in the app language
STATUS_REJECTED = "rejected"      # left empty; the English name is shown

# Product rule (2026-10-07): a spelling the engine reports below 65%
# confidence is not accepted — the Hindi name is left empty. The sound check
# and the ambiguity checks are hard gates in front of it: a spelling that
# does not sound like the name, or whose ending could be read two ways, is
# left empty whatever confidence the engine reports. There is no in-between
# state; owner confirmation of names is a later stage.
ACCEPT_CONFIDENCE = 0.65


# ── English side ──────────────────────────────────────────────────────────────

# Order matters: longer sequences first.
_ROMAN_FOLDS: tuple[tuple[str, str], ...] = (
    ("chh", "c"), ("ch", "c"), ("ngh", "nh"), ("sh", "s"), ("ph", "f"), ("kh", "k"),
    ("gh", "g"), ("jh", "j"), ("th", "t"), ("dh", "d"), ("bh", "b"), ("q", "k"),
    ("x", "ks"), ("z", "j"), ("w", "v"),
    ("aa", "a"), ("ee", "i"), ("ii", "i"), ("oo", "u"), ("uu", "u"),
    ("ou", "au"),
)
# Spellings of the same Hindi sound that are too common to reject on.
_ROMAN_WORD_ALIASES = {"shri": "sri", "shree": "sri", "sree": "sri", "sri": "sri"}

# How Hindi writes English letter names, for initials ("R. K. Sharma").
_LETTER_NAMES = {
    "a": "e", "b": "bi", "c": "si", "d": "di", "e": "i", "f": "ef", "g": "ji", "h": "ec",
    "i": "ai", "j": "je", "k": "ke", "l": "el", "m": "em", "n": "en", "o": "o", "p": "pi",
    "q": "kyu", "r": "ar", "s": "es", "t": "ti", "u": "yu", "v": "vi", "w": "dablyu",
    "x": "eks", "y": "vai", "z": "jed",
}


def roman_key(word: str) -> str:
    """Sound key of one English-letter word."""
    w = word.lower()
    if w in _ROMAN_WORD_ALIASES:
        return _ROMAN_WORD_ALIASES[w]
    if len(w) == 1:
        return _LETTER_NAMES.get(w, w)
    # A 'c' that is not part of 'ch' sounds like k ("Vicky", "Mac"). Done
    # before the folds, which turn 'ch' into 'c' (= च).
    w = re.sub(r"c(?!h)", "k", w)
    for a, b in _ROMAN_FOLDS:
        w = w.replace(a, b)
    # A final 'y' after a consonant is the vowel i: "Vicky" = विक्की. After a
    # vowel it stays a consonant: "Akshay" = अक्षय.
    w = re.sub(r"(?<=[^aeiou])y$", "i", w)
    # Nasal before a labial is written with anusvara in Hindi: Ambika = अंबिका.
    w = re.sub(r"m(?=[pb])", "n", w)
    w = re.sub(r"(.)\1+", r"\1", w)  # collapse doubles: "Pooja"->"puja", "Anna"->"ana"
    return w


# ── Devanagari side ───────────────────────────────────────────────────────────

_CONSONANTS = {
    "क": "k", "ख": "k", "ग": "g", "घ": "g", "ङ": "n",
    "च": "c", "छ": "c", "ज": "j", "झ": "j", "ञ": "n",
    "ट": "t", "ठ": "t", "ड": "d", "ढ": "d", "ण": "n",
    "त": "t", "थ": "t", "द": "d", "ध": "d", "न": "n",
    "प": "p", "फ": "f", "ब": "b", "भ": "b", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v",
    "श": "s", "ष": "s", "स": "s", "ह": "h",
}
_NUKTA_CONSONANTS = {"क": "k", "ख": "k", "ग": "g", "ज": "j", "ड": "d", "ढ": "d", "फ": "f", "य": "y"}
_INDEPENDENT_VOWELS = {
    "अ": "a", "आ": "a", "इ": "i", "ई": "i", "उ": "u", "ऊ": "u", "ऋ": "ri",
    "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऍ": "e", "ऑ": "o",
}
_MATRAS = {
    "ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "u", "ृ": "ri",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ॅ": "e", "ॉ": "o",
}
_VIRAMA, _NUKTA, _ANUSVARA, _CANDRABINDU, _VISARGA = "्", "़", "ं", "ँ", "ः"

_OPTIONAL_A = "\x00"   # placeholder for a medial inherent schwa: matches "a" or nothing


def _devanagari_units(word: str) -> Optional[list[str]]:
    """Letters of one Devanagari word as key pieces, or None if it holds
    anything this module does not understand (then the caller fails safe)."""
    w = unicodedata.normalize("NFC", word)
    units: list[str] = []
    i = 0
    while i < len(w):
        ch = w[i]
        nxt = w[i + 1] if i + 1 < len(w) else ""
        if ch in _CONSONANTS:
            base = _CONSONANTS[ch]
            if nxt == _NUKTA:
                base = _NUKTA_CONSONANTS.get(ch, base)
                i += 1
                nxt = w[i + 1] if i + 1 < len(w) else ""
            if nxt == _VIRAMA:
                units.append(base)
                i += 2
                continue
            if nxt in _MATRAS:
                units.append(base + _MATRAS[nxt])
                i += 2
                continue
            units.append(base + _OPTIONAL_A)   # inherent schwa, resolved below
            i += 1
            continue
        if ch in _INDEPENDENT_VOWELS:
            units.append(_INDEPENDENT_VOWELS[ch])
        elif ch in (_ANUSVARA, _CANDRABINDU):
            units.append("n")
        elif ch == _VISARGA:
            units.append("h")
        else:
            return None
        i += 1
    return units


def devanagari_pattern(word: str, final_a_optional: bool = False) -> Optional[re.Pattern]:
    """Regex the English sound key must match for this Devanagari word.
    Hindi drops the inherent "a" at the end of a word and often in the
    middle: final -> absent, medial -> optional."""
    units = _devanagari_units(word)
    if not units:
        return None
    # Hindi drops the inherent "a" of a word's last consonant (अक्षय = akshay)
    # — but not after a consonant cluster, where it is still said (आदित्य =
    # aditya, कृष्ण = krishna), so there it stays optional. Either way an
    # explicit vowel sign (अक्षया) is never optional: the final vowel is the
    # strict part of the check.
    if units[-1].endswith(_OPTIONAL_A):
        after_cluster = len(units) >= 2 and not any(c in "aeiou" for c in units[-2])             and _OPTIONAL_A not in units[-2] and units[-2] != "n"
        # final_a_optional (suggestions only — the person picks): a final
        # unwritten vowel may also be spelled "a" (Tathagat / Tathagata).
        if not after_cluster and not final_a_optional:
            units[-1] = units[-1][:-1]
    raw = "".join(units)
    # Doubled consonants on the English side were collapsed; collapse here too.
    raw = re.sub(r"(.)\1+", r"\1", raw.replace(_OPTIONAL_A, "\x01")).replace("\x01", _OPTIONAL_A)
    # A medial inherent "a" is often written e, u or o in English ("Verma"
    # वर्मा, "Bunty" बंटी, "Menon" मेनन, "Mohammed" मोहम्मद) — or left out. A
    # word-final one (kept only after a cluster: आदित्य) may only be "a": the
    # end of the word stays strict.
    last = len(raw) - 1
    body = "".join(
        ("a?" if i == last else "[aeou]?") if c == _OPTIONAL_A else re.escape(c)
        for i, c in enumerate(raw)
    )
    return re.compile(rf"^{body}$")


def devanagari_letter_key(word: str) -> Optional[str]:
    """Key of a Devanagari word read in full (no schwa games) — used for
    initials, which Hindi spells as letter names (आर, के)."""
    units = _devanagari_units(word)
    if not units:
        return None
    return "".join(u.replace(_OPTIONAL_A, "a") for u in units).rstrip("a") or None


# ── Decision ──────────────────────────────────────────────────────────────────

_ROMAN_WORD = re.compile(r"[A-Za-z]+")
_DEVANAGARI_WORD = re.compile(r"[ऀ-ॿ]+")


def normalize_spelling(devanagari_name: Optional[str]) -> Optional[str]:
    """NFC, single spaces, and no virama at the end of a word: Hindi writes
    "हेतल", not "हेतल्" (the engine was seen producing the latter). Apply
    before deciding and before storing."""
    if not devanagari_name:
        return devanagari_name
    s = unicodedata.normalize("NFC", devanagari_name)
    s = re.sub(rf"{_VIRAMA}(?=\s|$)", "", s)
    return " ".join(s.split())


@dataclass(frozen=True)
class NameVerdict:
    status: str                 # confident | rejected
    reason: str                 # why, for logs and review sheets


def sounds_the_same(english_name: str, devanagari_name: str, final_a_optional: bool = False) -> Optional[str]:
    """None if every word of the Devanagari spelling sounds like the matching
    English word; otherwise the reason it does not.

    final_a_optional relaxes one rule, for SUGGESTIONS the person chooses
    from: an English final "a" may stand for a Hindi word ending on a bare
    consonant (Tathagata / तथागत, Rama / राम). Automatic generation never
    uses it — there that ambiguity is exactly what must not be guessed."""
    en_words = _ROMAN_WORD.findall(english_name)
    hi_words = _DEVANAGARI_WORD.findall(devanagari_name)
    if not en_words:
        return "no English letters in the name"
    if len(en_words) != len(hi_words):
        return f"word count differs ({len(en_words)} vs {len(hi_words)})"
    if re.search(r"[A-Za-z]", devanagari_name):
        return "spelling still contains English letters"
    for en, hi in zip(en_words, hi_words):
        key = roman_key(en)
        if len(en) == 1:   # an initial: compare with the letter name
            if devanagari_letter_key(hi) != key:
                return f"initial {en!r} written as {hi!r}"
            continue
        pattern = devanagari_pattern(hi, final_a_optional)
        if pattern is None:
            return f"cannot read {hi!r}"
        if not any(pattern.match(k) for k in _key_variants(key)):
            return f"{hi!r} does not sound like {en!r}"
    return None


def _word_ending(word: str) -> str:
    """How a Devanagari word ends, as a sound class: the vowel sign or
    independent vowel it ends on (long and short i/u count as one), or
    "consonant" for a bare final consonant."""
    w = unicodedata.normalize("NFC", word)
    last = w[-1:] if w else ""
    if last in _MATRAS:
        return _MATRAS[last].replace("ii", "i")
    if last in _INDEPENDENT_VOWELS:
        return _INDEPENDENT_VOWELS[last]
    if last in (_ANUSVARA, _CANDRABINDU):
        return "nasal"
    return "consonant"


def _endings_differ(spelling: str, alternative: str) -> bool:
    """True if the alternative ends a word differently (कमला vs कमल) — a
    different name. False for a same-sound spelling variant (पाण्डेय vs
    पांडेय, चंद्र vs चन्द्र), which must not hold a name back."""
    a, b = _DEVANAGARI_WORD.findall(spelling), _DEVANAGARI_WORD.findall(alternative or "")
    if not b or b == a:
        return False
    if len(a) != len(b):
        return True
    return any(_word_ending(x) != _word_ending(y) for x, y in zip(a, b))


def _cluster_ending_is_ambiguous(english_name: str, devanagari_name: str) -> Optional[str]:
    """An English word ending in "a" after a consonant cluster ("Kavya",
    "Aditya") can be written with the vowel sign (काव्या) or without it
    (काव्य) — and those can be different names, of different gender. The sound
    check cannot tell them apart, so a spelling WITHOUT the vowel sign there is
    ambiguous: never shown, only suggested."""
    for en, hi in zip(_ROMAN_WORD.findall(english_name), _DEVANAGARI_WORD.findall(devanagari_name)):
        units = _devanagari_units(hi)
        if not units or len(en) < 2 or not en.lower().endswith("a"):
            continue
        if not units[-1].endswith(_OPTIONAL_A) or len(units) < 2:
            continue
        before = units[-2]
        if _OPTIONAL_A not in before and not any(c in "aeiou" for c in before) and before != "n":
            return f"final 'a' of {en!r} after a cluster could be long or short ({hi!r})"
    return None


def _key_variants(key: str) -> set[str]:
    """Spellings of the same sound: "ai" and "ay" (Jai जय, Nair नायर, Sai साई),
    and a final "ao" for "av" (Rao राव)."""
    out = {key, key.replace("ai", "ay"), key.replace("ay", "ai")}
    if key.endswith("ao"):
        out |= {k[:-2] + "av" for k in set(out)}
    return out


def decide(
    english_name: str,
    devanagari_name: Optional[str],
    confidence: Optional[float],
    alternative: Optional[str] = None,
) -> NameVerdict:
    """The product rule, all-or-nothing: accepted only if the spelling sounds
    like the name, its ending is unambiguous, and the engine reports at least
    65% confidence. Anything else is rejected and the Hindi name stays empty.

    `alternative` is another spelling the engine says the same English name
    could equally be ("Rama": रामा or राम). The engine reported 0.9+ for
    exactly these names in testing, so its confidence cannot settle them: a
    name with a plausible alternative ending is left empty.

    Pass the spelling through normalize_spelling() first; it is what gets
    stored."""
    if not devanagari_name or not devanagari_name.strip():
        return NameVerdict(STATUS_REJECTED, "no spelling returned")
    mismatch = sounds_the_same(english_name, devanagari_name)
    if mismatch:
        return NameVerdict(STATUS_REJECTED, mismatch)
    unsure = _cluster_ending_is_ambiguous(english_name, devanagari_name)
    if unsure:
        return NameVerdict(STATUS_REJECTED, unsure)
    if alternative and _endings_differ(devanagari_name, alternative):
        return NameVerdict(STATUS_REJECTED, f"could also be {alternative.strip()!r}")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        return NameVerdict(STATUS_REJECTED, "no confidence reported")
    if confidence < ACCEPT_CONFIDENCE:
        return NameVerdict(STATUS_REJECTED, f"confidence {confidence:.2f} below {ACCEPT_CONFIDENCE:.2f}")
    return NameVerdict(STATUS_CONFIDENT, f"sound check passed, confidence {confidence:.2f}")


def decide_romanization(
    devanagari_name: str,
    english_name: Optional[str],
    confidence: Optional[float],
) -> NameVerdict:
    """The other direction: a name the person typed in Devanagari, written
    in English letters by the engine. The Devanagari is the owner's own, so
    there is no ending ambiguity to guard against — only that the English
    sounds exactly the same (strictly: no final "a" added for an unwritten
    vowel, which could turn अक्षय into "Akshaya") and the 65% bar."""
    if not english_name or not english_name.strip():
        return NameVerdict(STATUS_REJECTED, "no spelling returned")
    if re.search(r"[^\x00-\x7F]", english_name):
        return NameVerdict(STATUS_REJECTED, "spelling is not in English letters")
    mismatch = sounds_the_same(english_name, devanagari_name)
    if mismatch:
        return NameVerdict(STATUS_REJECTED, mismatch)
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        return NameVerdict(STATUS_REJECTED, "no confidence reported")
    if confidence < ACCEPT_CONFIDENCE:
        return NameVerdict(STATUS_REJECTED, f"confidence {confidence:.2f} below {ACCEPT_CONFIDENCE:.2f}")
    return NameVerdict(STATUS_CONFIDENT, f"sound check passed, confidence {confidence:.2f}")


def readable_devanagari(text: Optional[str]) -> bool:
    """True if every word is Devanagari the sound check can read — the
    precondition for storing a Devanagari spelling we did not get from the
    person themselves."""
    words = (text or "").split()
    return bool(words) and all(_devanagari_units(w) for w in words)
