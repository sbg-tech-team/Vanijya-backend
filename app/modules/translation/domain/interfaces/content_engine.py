from __future__ import annotations

from abc import ABC, abstractmethod

from app.modules.translation.domain.prompt import AssembledPrompt


class IContentTranslationEngine(ABC):
    """Translates a JSON object of fields and returns the parsed JSON object.
    Shape checking is the caller's job (content.validate_shape), so a fake
    engine in tests can return anything and exercise that path."""

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        ...

    @abstractmethod
    def translate_fields(self, prompt: AssembledPrompt) -> object:
        ...
