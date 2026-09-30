"""Trade glossary for content translation.

Commodity and unit words were where native reviewers found most real errors
(2026-09 review of hi/mr/gu/pa/bn/ta): cotton came back as "কটুন" in Bengali
and "கப்பாய்" in Tamil, chana as "சுண்டல் பருப்பு", quintal misspelled
"ਕੁੰਤਲ". A short fixed glossary, sent only for the terms that actually appear
in the text, pins these words.

Every entry records where it came from:
  R = taken from a native reviewer's correction
  D = draft, not yet confirmed by a native speaker
Confirm or correct the D entries before relying on them; R entries can still
be overruled by a reviewer. Languages with no entries get no glossary.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

R, D = "reviewer", "draft"


@dataclass(frozen=True)
class GlossaryTerm:
    key: str                 # English label, as shown to the engine
    triggers: tuple[str, ...]  # words that make this entry apply (case-insensitive)
    targets: dict[str, tuple[str, str]]  # lang -> (word, source)


TERMS: tuple[GlossaryTerm, ...] = (
    GlossaryTerm("wheat", ("wheat", "gehu", "gehun", "gehoon", "गेहूं", "गेहूँ"), {
        "hi": ("गेहूं", R), "mr": ("गहू", R), "gu": ("ઘઉં", R), "pa": ("ਕਣਕ", R),
        "bn": ("গম", R), "ta": ("கோதுமை", R),
    }),
    GlossaryTerm("rice", ("rice", "chawal", "chaval", "चावल"), {
        "hi": ("चावल", D), "mr": ("तांदूळ", D), "gu": ("ચોખા", D), "pa": ("ਚੌਲ", R),
        "bn": ("চাল", D), "ta": ("அரிசி", D),
    }),
    GlossaryTerm("cotton (kapas)", ("cotton", "kapas", "कपास"), {
        "hi": ("कपास", R), "mr": ("कापूस", D), "gu": ("કપાસ", R), "pa": ("ਕਪਾਹ", R),
        "bn": ("কটন", R), "ta": ("பருத்தி", R),
    }),
    GlossaryTerm("sugar", ("sugar", "cheeni", "chini", "चीनी"), {
        "hi": ("चीनी", D), "mr": ("साखर", D), "gu": ("ખાંડ", D), "pa": ("ਸ਼ੂਗਰ", R),
        "bn": ("চিনি", D), "ta": ("சர்க்கரை", D),
    }),
    GlossaryTerm("maize", ("maize", "corn", "makka", "makki", "मक्का"), {
        "hi": ("मक्का", D), "mr": ("मका", R), "gu": ("મકાઈ", R), "pa": ("ਮੱਕੀ", D),
        "bn": ("ভুট্টা", R), "ta": ("மக்காச்சோளம்", R),
    }),
    GlossaryTerm("soybean", ("soybean", "soyabean", "soya", "सोयाबीन"), {
        "hi": ("सोयाबीन", D), "mr": ("सोयाबीन", R), "gu": ("સોયાબીન", R), "pa": ("ਸੋਇਆਬੀਨ", R),
        "bn": ("সয়াবিন", R), "ta": ("சோயாபீன்", R),
    }),
    GlossaryTerm("chana (chickpea)", ("chana", "chickpea", "chickpeas", "gram", "चना"), {
        "hi": ("चना", D), "mr": ("हरभरा", D), "gu": ("ચણા", R), "pa": ("ਛੋਲੇ", D),
        "bn": ("ছোলা", D), "ta": ("கொண்டைக்கடலை", R),
    }),
    GlossaryTerm("jeera (cumin)", ("jeera", "jira", "cumin", "जीरा"), {
        "hi": ("जीरा", R), "mr": ("जिरे", R), "gu": ("જીરૂ", R), "pa": ("ਜੀਰਾ", R),
        "bn": ("জিরা", R), "ta": ("சீரகம்", R),
    }),
    GlossaryTerm("quintal", ("quintal", "quintals", "qtl", "क्विंटल"), {
        "hi": ("क्विंटल", R), "mr": ("क्विंटल", R), "gu": ("ક્વિન્ટલ", R), "pa": ("ਕੁਇੰਟਲ", R),
        "bn": ("কুইন্টাল", R), "ta": ("குவிண்டால்", R),
    }),
    GlossaryTerm("bags (of produce)", ("bag", "bags", "bori", "बोरी"), {
        "hi": ("बोरी", D), "mr": ("बॅग्ज", R), "gu": ("બેગ", R), "pa": ("ਬੋਰੀਆਂ", D),
        "bn": ("বস্তা", D), "ta": ("மூட்டைகள்", R),
    }),
    GlossaryTerm("mandi (market yard)", ("mandi", "mandis", "मंडी"), {
        "hi": ("मंडी", R), "mr": ("मंडी", R), "gu": ("મંડી", R), "pa": ("ਮੰਡੀ", R),
        "bn": ("মান্ডি", R), "ta": ("மண்டி", R),
    }),
    GlossaryTerm("arrivals (produce reaching the mandi)", ("arrival", "arrivals", "aavak", "awak", "आवक"), {
        "hi": ("आवक", D), "mr": ("आवक", R), "gu": ("આવક", R), "pa": ("ਆਵਕ", R),
        "bn": ("আগমন", R), "ta": ("வரத்து", R),
    }),
    GlossaryTerm("crore", ("crore", "crores", "करोड़"), {
        "hi": ("करोड़", D), "mr": ("कोटी", D), "gu": ("કરોડ", D), "pa": ("ਕਰੋੜ", D),
        "bn": ("কোটি", R), "ta": ("கோடி", R),
    }),
    GlossaryTerm("lakh", ("lakh", "lakhs", "लाख"), {
        "hi": ("लाख", D), "mr": ("लाख", R), "gu": ("લાખ", R), "pa": ("ਲੱਖ", R),
        "bn": ("লাখ", R), "ta": ("லட்சம்", D),
    }),
)


def _pattern(term: GlossaryTerm) -> re.Pattern:
    # Whole words only: "gram" must not fire inside "program". Lookarounds
    # instead of \b so Devanagari triggers (with vowel signs) match too.
    alts = "|".join(re.escape(t) for t in sorted(term.triggers, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alts})(?!\w)", re.IGNORECASE)


_PATTERNS = tuple((term, _pattern(term)) for term in TERMS)


def glossary_for(texts: list[str], target_lang: str) -> list[tuple[str, str]]:
    """(English label, target word) for every term that appears in `texts`
    and has an entry for `target_lang`, in glossary order."""
    blob = "\n".join(texts)
    found = []
    for term, pattern in _PATTERNS:
        target = term.targets.get(target_lang)
        if target and pattern.search(blob):
            found.append((term.key, target[0]))
    return found
