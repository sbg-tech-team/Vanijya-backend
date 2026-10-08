from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator

from app.modules.translation.domain.prompt import LANGUAGE_NAMES, normalize_language
from app.modules.translation.domain.value_objects import CONTENT_MAX_ITEMS_PER_REQUEST


def _supported(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    lang = normalize_language(v)
    if lang is None:
        raise ValueError(f"unsupported language; one of {sorted(LANGUAGE_NAMES)}")
    return lang


class ContentItemIn(BaseModel):
    type: Literal["post", "comment", "news"]
    id: str = Field(min_length=1, max_length=64)
    # Narrow to what the screen shows — a news card needs title and
    # summary_bullets, not the detail fields. Omit for every field.
    fields: Optional[list[str]] = Field(default=None, max_length=10)


class TranslateContentRequest(BaseModel):
    items: list[ContentItemIn] = Field(min_length=1, max_length=CONTENT_MAX_ITEMS_PER_REQUEST)
    # Explicit override. Omit to use the app language / saved preference.
    target_lang: Optional[str] = None

    @field_validator("target_lang")
    @classmethod
    def _check_lang(cls, v: Optional[str]) -> Optional[str]:
        return _supported(v)


class ContentItemOut(BaseModel):
    type: str
    id: str
    # ready       -> `fields` holds every requested field that has text
    # in_progress -> another reader is translating it right now; retry shortly
    # failed      -> the engine failed or returned unusable output; retry later
    # not_found   -> no such item, or not visible to this reader
    status: Literal["ready", "in_progress", "failed", "not_found"]
    fields: Optional[dict[str, Union[str, list[str]]]] = None
    # True when served from a stored translation — no engine call was made.
    cached: bool = False


class TranslateContentResponse(BaseModel):
    lang: str
    items: list[ContentItemOut]


class TranslationPreferenceIn(BaseModel):
    target_lang: str

    @field_validator("target_lang")
    @classmethod
    def _check_lang(cls, v: str) -> str:
        return _supported(v)


class TranslationPreferenceOut(BaseModel):
    target_lang: Optional[str] = None
    supported: dict[str, str]


class NameSuggestionsRequest(BaseModel):
    # The name as the person is typing it, in any script.
    text: str = Field(min_length=1, max_length=100)
    # The language to suggest spellings in ("en" for a name typed in Hindi).
    to: str

    @field_validator("to")
    @classmethod
    def _check_to(cls, v: str) -> str:
        return _supported(v)


class NameSuggestionsResponse(BaseModel):
    source_lang: str          # language the name was typed in, from its script
    to: str
    suggestions: list[str]    # most common first; may be empty — the person can always type their own
