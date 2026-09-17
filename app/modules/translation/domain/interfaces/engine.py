from __future__ import annotations

from abc import ABC, abstractmethod

from app.modules.translation.domain.entities import EngineResponse
from app.modules.translation.domain.prompt import AssembledPrompt


class ITranslationEngine(ABC):
    """Swappable per CLAUDE.md — Gemini today, Sarvam Mayura as a named fallback
    if quality on real code-mixed data disappoints."""

    @abstractmethod
    def translate(self, prompt: AssembledPrompt) -> EngineResponse:
        ...
