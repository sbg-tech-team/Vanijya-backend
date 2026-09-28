"""
On-command translation of posts, comments and news.

POST /translate/content      -> translate the given items into the reader's language
GET  /translate/preference   -> the reader's saved translation language
PUT  /translate/preference   -> save it

Feeds and detail endpoints are untouched: the original text is always what
they return, and a translation is only ever shown alongside it, when the
reader asks. Chat keeps its own translate endpoints in the chat router.
"""
from __future__ import annotations

import logging
from typing import Optional

import redis as redis_lib
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse

from app.core import rate_limiter
from app.core.redis_client import get_redis
from app.dependencies import CurrentUser, get_current_user, get_current_user_id
from app.modules.translation.domain.content import ContentRef, canonical_id
from app.modules.translation.domain.exceptions import (
    LanguageNotChosenError,
    TranslationEngineUnavailableError,
)
from app.modules.translation.domain.prompt import LANGUAGE_NAMES
from app.modules.translation.domain.value_objects import (
    CONTENT_TRANSLATE_RATE_LIMIT,
    CONTENT_TRANSLATE_RATE_WINDOW_SECONDS,
)
from app.modules.translation.presentation.dependencies import (
    get_resolve_content_language_uc,
    get_translate_content_uc,
    get_translation_preference_uc,
)
from app.modules.translation.presentation.schemas import (
    ContentItemOut,
    TranslateContentRequest,
    TranslateContentResponse,
    TranslationPreferenceIn,
    TranslationPreferenceOut,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/translate", tags=["Translation"])


@router.post("/content", response_model=TranslateContentResponse)
def translate_content(
    body: TranslateContentRequest,
    user: CurrentUser = Depends(get_current_user),
    x_app_language: Optional[str] = Header(default=None),
    resolve_uc=Depends(get_resolve_content_language_uc),
    translate_uc=Depends(get_translate_content_uc),
    r: redis_lib.Redis = Depends(get_redis),
):
    """Translate posts, comments and news the reader tapped Translate on.

    Target language: `target_lang` in the body, else the app language
    (`X-App-Language` header) when it is not English, else the reader's saved
    preference. With none of those the response is 409 `language_required`
    and the app should ask the reader to pick one (PUT /translate/preference).

    Stored translations are returned without an engine call and never count
    against the rate limit; only a request that actually needs the engine does.
    """
    try:
        lang = resolve_uc.execute(user.user_id, body.target_lang, x_app_language)
    except LanguageNotChosenError as e:
        return JSONResponse(
            status_code=409,
            content={"detail": str(e), "code": "language_required",
                     "supported": LANGUAGE_NAMES},
        )

    def _rate_limit() -> None:
        try:
            rate_limiter.check(
                r, f"translate_content:{user.user_id}",
                limit=CONTENT_TRANSLATE_RATE_LIMIT, window=CONTENT_TRANSLATE_RATE_WINDOW_SECONDS,
            )
        except HTTPException:
            raise
        except Exception:
            # Redis down must not block translating; the limiter is a cost
            # guard, not a gate. Logged so an outage doesn't hide spend.
            log.warning("content translation rate limiting unavailable for %s", user.user_id)

    refs = [
        ContentRef(entity_type=i.type, entity_id=canonical_id(i.type, i.id),
                   fields=tuple(i.fields) if i.fields is not None else None)
        for i in body.items
    ]
    try:
        results = translate_uc.execute(
            viewer_profile_id=user.profile_id, refs=refs, target_lang=lang,
            before_engine_call=_rate_limit,
        )
    except TranslationEngineUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return TranslateContentResponse(
        lang=lang,
        items=[
            ContentItemOut(type=res.ref.entity_type, id=res.ref.entity_id,
                           status=res.status, fields=res.fields, cached=res.cached)
            for res in results
        ],
    )


@router.get("/preference", response_model=TranslationPreferenceOut)
def get_translation_preference(
    user_id=Depends(get_current_user_id),
    uc=Depends(get_translation_preference_uc),
):
    """Saved translation language (null if never set) and the supported set."""
    return TranslationPreferenceOut(target_lang=uc.get(user_id), supported=LANGUAGE_NAMES)


@router.put("/preference", response_model=TranslationPreferenceOut)
def set_translation_preference(
    body: TranslationPreferenceIn,
    user_id=Depends(get_current_user_id),
    uc=Depends(get_translation_preference_uc),
):
    """Used when the app runs in English. Also becomes chat's fallback language."""
    return TranslationPreferenceOut(target_lang=uc.set(user_id, body.target_lang),
                                    supported=LANGUAGE_NAMES)
