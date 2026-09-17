from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class ITranslationCache(ABC):
    """Server-side, in-memory, best-effort only — the durable copy of a
    translation lives on the reader's device, not in our DB. context_fingerprint
    (the current rolling summary, or "" when none) is part of the key so a
    context-dependent phrase never returns a translation cached under a
    different conversation state."""

    @abstractmethod
    def get(self, text: str, target_lang: str, context_fingerprint: str) -> Optional[str]:
        ...

    @abstractmethod
    def set(self, text: str, target_lang: str, context_fingerprint: str, translated_text: str) -> None:
        ...
