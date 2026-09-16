"""
Interaction routes — all user action endpoints.

Paths match app_v1_backup/modules/news_new/news_user_interaction/router.py
exactly (prefix "/interactions", mounted under "/news" by router.py):

POST /news/interactions/batch              -> bulk client event batch
POST /news/interactions/like/{id}          -> toggle like
POST /news/interactions/save/{id}          -> toggle save
POST /news/interactions/share/{id}         -> external share (WhatsApp, copy-link, etc.)
GET  /news/interactions/share-sheet/{id}   -> DM/group recipients for the share sheet
POST /news/interactions/send/{id}          -> in-app send via chat (multi-recipient)
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder

from app.modules.chat.presentation.dependencies import get_share_recipients_uc
from app.modules.news.application.use_cases.record_interaction import RecordInteractionUseCase
from app.modules.news.application.use_cases.send_article import SendArticleUseCase
from app.modules.news.domain.exceptions import ArticleNotFoundError
from app.modules.news.presentation.dependencies import (
    ProfileContextDep,
    RedisDep,
    get_record_interaction_use_case,
    get_send_article_use_case,
)
from app.modules.news.presentation.schemas import (
    NewsShareOut,
    NewsSendResponse,
    RecordEventsOut,
    RecordEventsRequest,
    SendArticleRequest,
    ToggleLikeOut,
    ToggleSaveOut,
)
from app.shared.utils.response import ok

router = APIRouter(prefix="/interactions", tags=["News Interactions"])


@router.post("/batch")
def submit_interaction_batch(
    body: RecordEventsRequest,
    profile: ProfileContextDep,
    use_case: Annotated[RecordInteractionUseCase, Depends(get_record_interaction_use_case)],
    rc: RedisDep,
):
    """
    Submit a batch of client-side interaction events (impression, dwell,
    open_article, share_tap). Events older than 2 hours or referencing
    unknown articles are silently dropped.
    """
    raw_events = [
        {
            "article_id": str(e.article_id),
            "event_type": e.event_type,
            "occurred_at": e.occurred_at,
            "value_ms": e.value_ms,
        }
        for e in body.events
    ]
    result = use_case.process_event_batch(profile_id=profile.profile_id, raw_events=raw_events, rc=rc)
    out = RecordEventsOut(**result)
    return ok(out.model_dump(mode="json"), "Batch processed")


@router.post("/like/{article_id}")
def toggle_like(
    article_id: UUID,
    profile: ProfileContextDep,
    use_case: Annotated[RecordInteractionUseCase, Depends(get_record_interaction_use_case)],
    rc: RedisDep,
):
    """Toggle like on an article. Returns the new like state."""
    try:
        result = use_case.toggle_like(profile_id=profile.profile_id, article_id=article_id, rc=rc)
    except ArticleNotFoundError:
        raise HTTPException(status_code=404, detail="Article not found")
    out = ToggleLikeOut(article_id=article_id, is_liked=result["is_liked"])
    return ok(out.model_dump(mode="json"), "Like toggled")


@router.post("/save/{article_id}")
def toggle_save(
    article_id: UUID,
    profile: ProfileContextDep,
    use_case: Annotated[RecordInteractionUseCase, Depends(get_record_interaction_use_case)],
    rc: RedisDep,
):
    """Toggle save on an article. Returns the new save state."""
    try:
        result = use_case.toggle_save(profile_id=profile.profile_id, article_id=article_id, rc=rc)
    except ArticleNotFoundError:
        raise HTTPException(status_code=404, detail="Article not found")
    out = ToggleSaveOut(article_id=article_id, is_saved=result["is_saved"])
    return ok(out.model_dump(mode="json"), "Save toggled")


@router.post("/share/{article_id}")
def record_share(
    article_id: UUID,
    profile: ProfileContextDep,
    use_case: Annotated[RecordInteractionUseCase, Depends(get_record_interaction_use_case)],
    rc: RedisDep,
    platform: str | None = Query(None, description="Platform the user shared to (whatsapp, copy, etc.)"),
):
    """External share only — increments share_count without delivering any
    in-app message. Use when the user shares via WhatsApp, copy link, or any
    channel outside the app."""
    try:
        use_case.record_share(profile_id=profile.profile_id, article_id=article_id, platform=platform, rc=rc)
    except ArticleNotFoundError:
        raise HTTPException(status_code=404, detail="Article not found")
    out = NewsShareOut(article_id=article_id, platform=platform)
    return ok(out.model_dump(mode="json"), "Shared successfully")


@router.get("/share-sheet/{article_id}")
def get_news_share_recipients(
    article_id: UUID,
    profile: ProfileContextDep,
    share_uc=Depends(get_share_recipients_uc),
):
    """
    Called when the user taps Share on a news article.
    Returns DM connections and groups the user can forward the article to.
    Identical data shape as GET /connections/share-recipients.
    """
    # chat owns this data — go through its use case, not its repository
    result = share_uc.execute(profile.user_id)
    return ok(result, "Share recipients fetched")


@router.post("/send/{article_id}", response_model=NewsSendResponse)
def send_news_article(
    article_id: UUID,
    body: SendArticleRequest,
    background_tasks: BackgroundTasks,
    profile: ProfileContextDep,
    use_case: Annotated[SendArticleUseCase, Depends(get_send_article_use_case)],
    rc: RedisDep,
):
    """
    In-app news share: delivers the article as a 'news_article' chat message
    to selected DMs and groups, then increments share_count once.
    """
    from app.core.realtime import emit_to_group, emit_to_user

    try:
        result = use_case.execute(
            sender_profile_id=profile.profile_id,
            sender_user_id=profile.user_id,
            article_id=article_id,
            dm_conversation_ids=body.dm_conversation_ids,
            group_ids=body.group_ids,
            caption=body.caption,
            rc=rc,
        )
    except ArticleNotFoundError:
        raise HTTPException(status_code=404, detail="Article not found")

    for receiver_id, msg in result["dm_deliveries"]:
        background_tasks.add_task(emit_to_user, receiver_id, "new_message", jsonable_encoder(msg))
    for group_id, msg in result["group_deliveries"]:
        background_tasks.add_task(emit_to_group, group_id, "new_group_message", jsonable_encoder(msg))

    return NewsSendResponse(
        share_count=result["share_count"],
        delivered_to=len(result["dm_deliveries"]) + len(result["group_deliveries"]),
    )
