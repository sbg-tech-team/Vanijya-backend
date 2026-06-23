import uuid as _uuid

from sqlalchemy.orm import Session

from app.modules.post.models import Post
from app.modules.news_new.ingestion.models import RawArticle
from app.modules.profile.models import Profile

APP_SCHEME = "vanijyaa"
PLAY_STORE_URL = "https://play.google.com/store/apps/details?id=com.vanijyaa.app"


class DeepLinkNotFoundError(Exception):
    pass


# ---------------------------------------------------------------------------
# Post
# ---------------------------------------------------------------------------

def get_post_share_link(db: Session, post_id: int) -> dict:
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise DeepLinkNotFoundError("Post not found")

    profile = db.query(Profile).filter(Profile.id == post.profile_id).first()
    poster_name = profile.name if profile else "Vanijyaa User"

    deep_link = f"{APP_SCHEME}://post/{post_id}"
    description = (post.caption[:120] + "...") if post.caption and len(post.caption) > 120 else post.caption
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
        "image_url": post.image_urls[0] if post.image_urls else None,
    }


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------

def get_news_share_link(db: Session, article_id: str) -> dict:
    try:
        uid = _uuid.UUID(article_id)
    except ValueError:
        raise DeepLinkNotFoundError("Invalid article ID")

    article = db.query(RawArticle).filter(RawArticle.id == uid).first()
    if not article:
        raise DeepLinkNotFoundError("Article not found")

    deep_link = f"{APP_SCHEME}://news/{article_id}"
    summary = article.description or article.api_summary
    description = (summary[:120] + "...") if summary and len(summary) > 120 else summary
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


# ---------------------------------------------------------------------------
# User / Profile
# ---------------------------------------------------------------------------

def get_user_share_link(db: Session, profile_id: int) -> dict:
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        raise DeepLinkNotFoundError("Profile not found")

    deep_link = f"{APP_SCHEME}://user/{profile_id}"
    parts = [p for p in [profile.business.business_name, profile.business.city] if p]
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
