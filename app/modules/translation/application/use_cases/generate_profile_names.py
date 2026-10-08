from __future__ import annotations

import logging
from collections import Counter
from typing import Optional

from app.modules.translation.domain.interfaces.content_engine import IContentTranslationEngine
from app.modules.translation.domain.interfaces.profile_names_repository import (
    IProfileNamesRepository,
    ProfileName,
)
from app.modules.translation.domain.names import (
    merge_owner_names,
    names_to_generate,
    script_language,
    with_failed,
    with_generated,
)
from app.modules.translation.domain.script_convert import SAME_FAMILY_BLOCKS, to_devanagari
from app.modules.translation.domain.transliteration import (
    STATUS_CONFIDENT,
    decide,
    decide_romanization,
    normalize_spelling,
    readable_devanagari,
)
from app.modules.translation.domain.transliteration_prompt import (
    assemble_both_scripts_prompt,
    assemble_romanization_prompt,
    assemble_transliteration_prompt,
)
from app.modules.translation.domain.value_objects import (
    NAME_GENERATION_BATCH,
    NAME_GENERATION_PER_RUN,
    NAME_TARGET_LANGUAGES,
)

log = logging.getLogger(__name__)

# Scripts the engine writes in both Hindi and English at once, cross-checked
# (they cannot be converted letter-for-letter: see script_convert).
_BOTH_SCRIPTS = {"ta", "ur"}


class GenerateProfileNamesUseCase:
    """Fills in the languages missing from a person's name_i18n (English and
    Hindi), whatever script the name was typed in. Three routes:

    * English -> Hindi: the engine proposes, the strict rule decides (sound
      check, no ambiguous ending, >= 65%).
    * Devanagari -> English: from a name typed in Hindi/Marathi, or from the
      Devanagari of a "same-family" script (Gujarati, Punjabi, Bengali,
      Telugu, Kannada, Malayalam), which is converted to Devanagari by fixed
      rules first — exact, no AI. The English is then checked against that
      Devanagari: same sound, no final "a" added, >= 65%.
    * Tamil / Urdu -> both: the engine writes Hindi and English together;
      accepted only if the two sound the same as each other and >= 65%.

    Accepted values are stored and listed under "auto". Rejected ones stay
    empty and are marked "failed", so they are not retried until the name
    changes or its owner types a spelling. Writes only if the profile is
    unchanged since it was read: an owner's edit made meanwhile always wins.
    """

    def __init__(self, repository: IProfileNamesRepository, engine: IContentTranslationEngine):
        self.repository = repository
        self.engine = engine

    def run(self, limit: int = NAME_GENERATION_PER_RUN) -> dict:
        """Scheduled backfill: up to `limit` profiles."""
        return self._process(self.repository.profiles_missing_names(NAME_TARGET_LANGUAGES, limit))

    def for_profile(self, profile_id: int) -> dict:
        """Right after a profile is created or its name edited."""
        p = self.repository.get(profile_id)
        return self._process([p] if p else [])

    # ─────────────────────────────────────────────────────────────────────────

    def _process(self, profiles: list[ProfileName]) -> dict:
        stats: Counter = Counter()
        if not profiles:
            return dict(stats)

        before = {p.profile_id: p for p in profiles}
        results: dict[int, dict] = {}       # profile_id -> new name_i18n
        to_hindi: list[tuple[ProfileName, str]] = []       # (profile, English name)
        to_english: list[tuple[ProfileName, str]] = []     # (profile, Devanagari)
        to_both: list[tuple[ProfileName, str, list[str]]] = []   # (profile, Tamil/Urdu name, targets)

        for p in profiles:
            src = script_language(p.name)
            current = p.name_i18n or merge_owner_names(p.name, None, existing=None, name_changed=True)
            if not p.name_i18n:
                results[p.profile_id] = current   # existing profile: seed with the typed name
            needed = names_to_generate(p.name, p.name_i18n, NAME_TARGET_LANGUAGES)
            if not needed:
                continue

            if src == "en":
                to_hindi.append((p, p.name))
            elif src == "hi":
                to_english.append((p, p.name))
            elif src in SAME_FAMILY_BLOCKS:
                devanagari = current.get("hi") or normalize_spelling(to_devanagari(p.name, src))
                if not readable_devanagari(devanagari):
                    for t in needed:
                        current = with_failed(current, t)
                    results[p.profile_id] = current
                    stats["rejected"] += len(needed)
                    continue
                if "hi" in needed:
                    current = with_generated(current, "hi", devanagari)   # exact, rule-based
                    results[p.profile_id] = current
                    stats["accepted"] += 1
                if "en" in needed:
                    to_english.append((p, devanagari))
            elif src in _BOTH_SCRIPTS:
                to_both.append((p, p.name, needed))
            else:
                for t in needed:
                    current = with_failed(current, t)
                results[p.profile_id] = current
                stats["unsupported_script"] += 1

        if (to_hindi or to_english or to_both) and not self.engine.is_configured:
            log.warning("name generation skipped: engine not configured")
            to_hindi, to_english, to_both = [], [], []

        for i in range(0, len(to_hindi), NAME_GENERATION_BATCH):
            self._to_hindi(to_hindi[i:i + NAME_GENERATION_BATCH], before, results, stats)
        for i in range(0, len(to_english), NAME_GENERATION_BATCH):
            self._to_english(to_english[i:i + NAME_GENERATION_BATCH], before, results, stats)
        for i in range(0, len(to_both), NAME_GENERATION_BATCH):
            self._to_both(to_both[i:i + NAME_GENERATION_BATCH], before, results, stats)

        for profile_id, name_i18n in results.items():
            if self.repository.save_if_unchanged(before[profile_id], name_i18n):
                stats["saved"] += 1
            else:
                stats["skipped_changed"] += 1
        return dict(stats)

    # ── routes ────────────────────────────────────────────────────────────────

    def _call(self, prompt, label: str, size: int, stats: Counter) -> Optional[dict]:
        try:
            out = self.engine.translate_fields(prompt)
        except Exception as exc:
            # An outage is not a verdict on the names: nothing is marked
            # failed, the next run tries again.
            log.warning("name generation (%s, %d names) failed: %s", label, size, exc)
            stats["engine_errors"] += 1
            return None
        return out if isinstance(out, dict) else {}

    @staticmethod
    def _current(p: ProfileName, results: dict) -> dict:
        return results.get(p.profile_id) or p.name_i18n or {}

    def _record(self, p, results, stats, target, spelling, verdict) -> None:
        current = self._current(p, results)
        if verdict.status == STATUS_CONFIDENT:
            results[p.profile_id] = with_generated(current, target, spelling)
            stats["accepted"] += 1
        else:
            results[p.profile_id] = with_failed(current, target)
            stats["rejected"] += 1
            log.info("name %s for profile %s not accepted: %s", target, p.profile_id, verdict.reason)

    def _to_hindi(self, group, before, results, stats) -> None:
        out = self._call(assemble_transliteration_prompt({f"p{p.profile_id}": n for p, n in group}),
                         "en->hi", len(group), stats)
        if out is None:
            return
        for p, english in group:
            got = out.get(f"p{p.profile_id}") or {}
            spelling = normalize_spelling(got.get("hi")) if isinstance(got.get("hi"), str) else None
            verdict = decide(english, spelling, got.get("confidence"), got.get("alt"))
            self._record(p, results, stats, "hi", spelling, verdict)

    def _to_english(self, group, before, results, stats) -> None:
        out = self._call(assemble_romanization_prompt({f"p{p.profile_id}": d for p, d in group}),
                         "dev->en", len(group), stats)
        if out is None:
            return
        for p, devanagari in group:
            got = out.get(f"p{p.profile_id}") or {}
            spelling = " ".join(got["en"].split()) if isinstance(got.get("en"), str) else None
            verdict = decide_romanization(devanagari, spelling, got.get("confidence"))
            self._record(p, results, stats, "en", spelling, verdict)

    def _to_both(self, group, before, results, stats) -> None:
        out = self._call(assemble_both_scripts_prompt({f"p{p.profile_id}": n for p, n, _ in group}),
                         "ta/ur->both", len(group), stats)
        if out is None:
            return
        for p, _name, needed in group:
            got = out.get(f"p{p.profile_id}") or {}
            hindi = normalize_spelling(got.get("hi")) if isinstance(got.get("hi"), str) else None
            english = " ".join(got["en"].split()) if isinstance(got.get("en"), str) else None
            readable = readable_devanagari(hindi)
            # Accepted only as a pair: the Hindi and English must sound the
            # same as each other — the one check available without a way to
            # read Tamil or Urdu script ourselves.
            verdict = decide_romanization(hindi, english, got.get("confidence")) if readable else None
            for target in needed:
                value = hindi if target == "hi" else english
                if verdict is not None:
                    self._record(p, results, stats, target, value, verdict)
                else:
                    results[p.profile_id] = with_failed(self._current(p, results), target)
                    stats["rejected"] += 1
