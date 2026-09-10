"""Share-link use cases.

The returned dicts and the exact `share_text` layout are ported character-for-
character from app_old/modules/deeplink/service.py — the client renders this
text directly.
"""
from __future__ import annotations

import uuid as _uuid

from app.modules.deeplink.domain.exceptions import DeepLinkNotFoundError
from app.modules.deeplink.domain.interfaces.repository import IDeepLinkRepository

APP_SCHEME = "vanijyaa"
PLAY_STORE_URL = "https://play.google.com/store/apps/details?id=com.vanijyaa.app"

_DEFAULT_POSTER_NAME = "Vanijyaa User"


def _truncate(text: str | None) -> str | None:
    """app_old rule: cut at 120 chars and append an ellipsis."""
    return (text[:120] + "...") if text and len(text) > 120 else text


def get_post_share_link(repo: IDeepLinkRepository, post_id: int) -> dict:
    post = repo.get_post(post_id)
    if not post:
        raise DeepLinkNotFoundError("Post not found")

    poster_name = post.author_name or _DEFAULT_POSTER_NAME
    deep_link = f"{APP_SCHEME}://post/{post_id}"
    description = _truncate(post.caption)
    share_text = (
        f"{poster_name} shared a post on Vanijyaa\n\n"
        f"{description or ''}\n\n"
        f"Open in app: {deep_link}\n"
        f"Download Vanijyaa: {PLAY_STORE_URL}"
    ).strip()

    return {
        "deep_link": deep_link,
        "share_text": share_text,
        "title": f"Post by {poster_name}",
        "description": description,
        "image_url": post.image_url,
    }


def get_news_share_link(repo: IDeepLinkRepository, article_id: str) -> dict:
    try:
        uid = _uuid.UUID(article_id)
    except ValueError:
        raise DeepLinkNotFoundError("Invalid article ID")

    article = repo.get_article(uid)
    if not article:
        raise DeepLinkNotFoundError("Article not found")

    deep_link = f"{APP_SCHEME}://news/{article_id}"
    description = _truncate(article.summary)
    share_text = (
        f"{article.title}\n\n"
        f"{description or ''}\n\n"
        f"Open in Vanijyaa: {deep_link}\n"
        f"Download Vanijyaa: {PLAY_STORE_URL}"
    ).strip()

    return {
        "deep_link": deep_link,
        "share_text": share_text,
        "title": article.title,
        "description": description,
        "image_url": article.image_url,
    }


def get_user_share_link(repo: IDeepLinkRepository, profile_id: int) -> dict:
    profile = repo.get_profile(profile_id)
    if not profile:
        raise DeepLinkNotFoundError("Profile not found")

    deep_link = f"{APP_SCHEME}://user/{profile_id}"
    parts = [p for p in [profile.business_name, profile.city] if p]
    description = " · ".join(parts) if parts else None
    share_text = (
        f"Connect with {profile.name} on Vanijyaa\n\n"
        f"{description + chr(10) if description else ''}"
        f"Open in app: {deep_link}\n"
        f"Download Vanijyaa: {PLAY_STORE_URL}"
    ).strip()

    return {
        "deep_link": deep_link,
        "share_text": share_text,
        "title": profile.name,
        "description": description,
        "image_url": profile.avatar_url,
    }
