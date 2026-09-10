"""SQLAlchemy implementation of IDeepLinkRepository.

Only file in the deeplink module that touches the database. Queries are ported
from app_old/modules/deeplink/service.py.

News reads `news_raw_articles` (RawArticle): the live news pipeline (GNews +
Groq) writes this table and the feed hands the client these ids, so the deep
link resolves the id the client actually has. There is no single `summary`
column on RawArticle — `description or api_summary` is the same fallback
chain app_old used.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.deeplink.domain.entities import ShareArticle, SharePost, ShareProfile
from app.modules.deeplink.domain.interfaces.repository import IDeepLinkRepository
from app.modules.news.data.models import RawArticle
from app.modules.post.data.models import Post
from app.modules.profile.data.models import Profile


class DeepLinkRepository(IDeepLinkRepository):

    def __init__(self, db: Session):
        self.db = db

    def get_post(self, post_id: int) -> SharePost | None:
        post = self.db.query(Post).filter(Post.id == post_id).first()
        if not post:
            return None
        profile = self.db.query(Profile).filter(Profile.id == post.profile_id).first()
        return SharePost(
            post_id=post.id,
            caption=post.caption,
            image_url=post.image_urls[0] if post.image_urls else None,
            author_name=profile.name if profile else None,
        )

    def get_article(self, article_id: UUID) -> ShareArticle | None:
        article = self.db.query(RawArticle).filter(RawArticle.id == article_id).first()
        if not article:
            return None
        return ShareArticle(
            title=article.title,
            summary=article.description or article.api_summary,
            image_url=article.image_url,
        )

    def get_profile(self, profile_id: int) -> ShareProfile | None:
        profile = self.db.query(Profile).filter(Profile.id == profile_id).first()
        if not profile:
            return None
        # business is a 1:1 that may legitimately be absent; app_old dereferenced
        # it unguarded and raised AttributeError -> HTTP 500.
        business = profile.business
        return ShareProfile(
            profile_id=profile.id,
            name=profile.name,
            avatar_url=profile.avatar_url,
            business_name=business.business_name if business else None,
            city=business.city if business else None,
        )
