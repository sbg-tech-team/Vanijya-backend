from __future__ import annotations

from typing import Optional

from google import genai
from google.genai import types
from pydantic import BaseModel

from app.modules.translation.domain.entities import EngineResponse
from app.modules.translation.domain.exceptions import TranslationEngineUnavailableError
from app.modules.translation.domain.interfaces.engine import ITranslationEngine
from app.modules.translation.domain.prompt import AssembledPrompt


class _StructuredOutput(BaseModel):
    translated_text: str
    updated_summary: Optional[str] = None
    chosen_target_lang: Optional[str] = None


class GeminiTranslationEngine(ITranslationEngine):
    """Static system_instruction is passed unchanged on every call by design —
    that consistency is what lets the engine's own prefix caching apply to it.
    Structured (JSON) output is only requested when the call also needs a
    summary refresh or is resolving AUTO_FALLBACK; the plain path stays a bare
    text response, since output tokens are the cost-dominant part.

    The genai.Client is built lazily, not in __init__ — constructing it with
    no key raises immediately, and this class is instantiated as a
    module-level singleton at import time (see presentation/dependencies.py).
    An absent key must degrade to "not configured" on first real use, the
    same way StreamVideoProvider handles an absent Stream key, rather than
    crashing every import of the chat router in any environment without the
    key set (CI included)."""

    def __init__(self, api_key: Optional[str], model: str):
        self._api_key = api_key
        self._model = model
        self._client: Optional[genai.Client] = None

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> genai.Client:
        if self._client is None:
            if not self.is_configured:
                raise TranslationEngineUnavailableError("Gemini API key is not configured")
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def translate(self, prompt: AssembledPrompt) -> EngineResponse:
        client = self._get_client()

        if prompt.structured_output:
            config = types.GenerateContentConfig(
                system_instruction=prompt.system_instruction,
                response_mime_type="application/json",
                response_schema=_StructuredOutput,
            )
        else:
            config = types.GenerateContentConfig(system_instruction=prompt.system_instruction)

        response = client.models.generate_content(
            model=self._model,
            contents=prompt.user_content,
            config=config,
        )

        if prompt.structured_output:
            parsed = _StructuredOutput.model_validate_json(response.text)
            return EngineResponse(
                translated_text=parsed.translated_text,
                updated_summary=parsed.updated_summary,
                chosen_target_lang=parsed.chosen_target_lang,
            )
        return EngineResponse(translated_text=response.text.strip())
