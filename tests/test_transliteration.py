"""
tests/test_transliteration.py

The confidence check for writing people's names in Hindi. Pure rules, no
engine. The cases come from a live run of 85 names against Gemini
(2026-10-07) — every one that went wrong at some point is pinned here.

    pytest tests/test_transliteration.py -v
"""
import pytest

from app.modules.translation.domain.transliteration import (
    STATUS_CONFIDENT,
    STATUS_REJECTED,
    decide,
    normalize_spelling,
    sounds_the_same,
)
from app.modules.translation.domain.transliteration_prompt import (
    TRANSLITERATION_SYSTEM_INSTRUCTION,
    assemble_transliteration_prompt,
)


# ── The non-negotiable: a name's ending is never swapped ──────────────────────

@pytest.mark.parametrize("english, wrong", [
    ("Akshay", "अक्षया"), ("Akshaya", "अक्षय"),
    ("Priya", "प्रिय"), ("Sumit", "सुमिता"), ("Ankita", "अंकित"),
    ("Shrey", "श्रेया"), ("Shreya", "श्रेय"), ("Pranav", "प्रणवी"),
])
def test_a_changed_ending_is_always_rejected(english, wrong):
    assert sounds_the_same(english, wrong) is not None
    assert decide(english, wrong, 0.99).status == STATUS_REJECTED


@pytest.mark.parametrize("english, devanagari", [
    ("Akshay", "अक्षय"), ("Akshaya", "अक्षया"), ("Ankit", "अंकित"), ("Ankita", "अंकिता"),
    ("Shrey", "श्रेय"), ("Shreya", "श्रेया"), ("Rahul Sharma", "राहुल शर्मा"),
    ("Pooja Gupta", "पूजा गुप्ता"), ("Puja", "पूजा"), ("Kamla", "कमला"),
    ("Ramandeep Singh Gill", "रमनदीप सिंह गिल"), ("R K Sharma", "आर के शर्मा"),
    ("Shri Ram Kumar", "श्री राम कुमार"), ("Vicky", "विक्की"), ("Ambika", "अंबिका"),
    # English writes Hindi's medial short "a" as e/u/o, and ai/ay are one sound
    ("Sanjay Verma", "संजय वर्मा"), ("Bunty", "बंटी"), ("Arjun Menon", "अर्जुन मेनन"),
    ("Mohammed Irfan", "मोहम्मद इरफ़ान"), ("Jai", "जय"), ("Sai", "साई"),
    ("Priya Nair", "प्रिया नायर"), ("Srinivas Rao", "श्रीनिवास राव"), ("Vivek Pandey", "विवेक पांडेय"),
])
def test_correct_spellings_pass_and_are_shown_when_confident(english, devanagari):
    assert sounds_the_same(english, devanagari) is None
    assert decide(english, devanagari, 0.95).status == STATUS_CONFIDENT


def test_wrong_spellings_the_engine_actually_produced_are_rejected():
    assert decide("Sachin Kulkarni", "सचिन कुलकणी", 0.85).status == STATUS_REJECTED   # dropped र्
    assert decide("Ramandeep Singh Gill", "रमनदीप सिंह गिल्स", 0.85).status == STATUS_REJECTED
    assert decide("Rahul", "राहुल शर्मा", 0.99).status == STATUS_REJECTED              # word added
    assert decide("Rahul", "Rahul", 0.99).status == STATUS_REJECTED                   # not Devanagari


# ── Ambiguity: never shown, the Hindi name stays empty ────────────────────────

def test_cluster_final_a_is_ambiguous_kavya_aditya():
    # The engine wrote काव्य for "Kavya" at 0.95 — the wrong name. Without the
    # vowel sign after a cluster the ending could be either, so never shown.
    assert decide("Kavya", "काव्य", 0.95).status == STATUS_REJECTED
    assert decide("Aditya", "आदित्य", 0.95).status == STATUS_REJECTED
    # With the vowel sign it is unambiguous.
    assert decide("Kavya", "काव्या", 0.95).status == STATUS_CONFIDENT


def test_an_alternative_with_a_different_ending_holds_the_name_back():
    # Rama / Shiva / Harsha came back at 0.9 confidence — confidence alone
    # cannot settle them.
    assert decide("Rama", "रामा", 0.9, "राम").status == STATUS_REJECTED
    assert decide("Kamla", "कमला", 0.95, "कमल").status == STATUS_REJECTED


def test_a_same_sound_alternative_does_not_hold_the_name_back():
    assert decide("Ramesh Pandey", "रमेश पांडेय", 0.95, "रमेश पाण्डेय").status == STATUS_CONFIDENT
    assert decide("Debashish", "देबाशीष", 0.95, "देबाशिष").status == STATUS_CONFIDENT


# ── The product thresholds ────────────────────────────────────────────────────

def test_confidence_threshold_is_65_percent_all_or_nothing():
    assert decide("Rahul", "राहुल", 0.65).status == STATUS_CONFIDENT
    assert decide("Rahul", "राहुल", 0.9).status == STATUS_CONFIDENT
    assert decide("Rahul", "राहुल", 0.64).status == STATUS_REJECTED
    assert decide("Rahul", "राहुल", None).status == STATUS_REJECTED
    assert decide("Rahul", "राहुल", True).status == STATUS_REJECTED     # not a number
    assert decide("Rahul", "", 0.99).status == STATUS_REJECTED
    # High confidence never overrides the sound check.
    assert decide("Akshay", "अक्षया", 0.99).status == STATUS_REJECTED


def test_normalize_spelling_drops_a_trailing_virama():
    assert normalize_spelling("हेतल्  देसाई") == "हेतल देसाई"
    assert decide("Hetal Desai", normalize_spelling("हेतल् देसाई"), 0.95).status == STATUS_CONFIDENT


def test_prompt_asks_for_alternative_and_confidence():
    p = assemble_transliteration_prompt({"n1": "Akshaya"})
    assert '"Akshaya"' in p.user_content and p.structured_output
    for must in ("'Akshay' is", "alt", "confidence", "letter names"):
        assert must in TRANSLITERATION_SYSTEM_INSTRUCTION
