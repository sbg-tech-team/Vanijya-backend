from __future__ import annotations

from typing import Optional

from google import genai
from google.genai import types
from pydantic import BaseModel

from app.modules.translation.domain.entities import EngineResponse
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
    text response, since output tokens are the cost-dominant part."""

    def __init__(self, api_key: str, model: str):
        self._client = genai.Client(api_key=api_key)
        self._model = model

    def translate(self, prompt: AssembledPrompt) -> EngineResponse:
        if prompt.structured_output:
            config = types.GenerateContentConfig(
                system_instruction=prompt.system_instruction,
                response_mime_type="application/json",
                response_schema=_StructuredOutput,
            )
        else:
            config = types.GenerateContentConfig(system_instruction=prompt.system_instruction)

        response = self._client.models.generate_content(
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
