"""SQLAlchemy implementation of IPostRepository.

The only file in the post module that touches the database. Query bodies,
eager-load strategies (selectinload vs joinedload), ordering, cursor filters
and the duplicate-view IntegrityError handling are moved verbatim from the
use-case files.

Transaction control stays with the caller where the use cases own multi-step
writes, so add/delete/commit/flush/refresh/rollback are exposed directly.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.modules.connections.data.models import UserConnection
from app.modules.post.data.models import Post, PostComment, PostLike, PostSave, PostView
from app.modules.post.recommendation.models import SeenPost
from app.modules.post.domain.interfaces.repository import IPostRepository
from app.modules.profile.data.models import Profile


class PostRepository(IPostRepository):

    def __init__(self, db: Session):
        self.db = db

    # -- unit of work ----------------------------------------------------------

    @property
    def session(self) -> Session:
        """Escape hatch for cross-module helpers that still take a Session."""
        return self.db

    def add(self, obj) -> None: self.db.add(obj)
    def delete(self, obj) -> None: self.db.delete(obj)
    def flush(self) -> None: self.db.flush()
    def commit(self) -> None: self.db.commit()
    def rollback(self) -> None: self.db.rollback()
    def refresh(self, obj) -> None: self.db.refresh(obj)

    # -- profiles --------------------------------------------------------------

    def active_profile_ids(self) -> list[int]:
        return [row[0] for row in self.db.query(Profile.id).all()]

    def get_profile(self, profile_id: int) -> Optional[Profile]:
        return self.db.query(Profile).filter(Profile.id == profile_id).first()

    def get_profile_by_user(self, user_id: UUID) -> Optional[Profile]:
        return self.db.query(Profile).filter(Profile.users_id == user_id).first()

    def get_profile_with_business(self, profile_id: int) -> Optional[Profile]:
        return (
            self.db.query(Profile)
            .options(selectinload(Profile.business))
            .filter(Profile.id == profile_id)
            .first()
        )

    def get_profile_with_commodities(self, profile_id: int) -> Optional[Profile]:
        return (
            self.db.query(Profile)
            .options(selectinload(Profile.commodities))
            .filter(Profile.id == profile_id)
            .first()
        )

    def get_authors_with_business(self, profile_ids: list[int]) -> dict:
        return {
            p.id: p
            for p in self.db.query(Profile)
            .options(selectinload(Profile.business))
            .filter(Profile.id.in_(profile_ids))
            .all()
        }

    def get_user_id_for_profile(self, profile_id: int):
        row = self.db.query(Profile.users_id).filter(Profile.id == profile_id).first()
        return row[0] if row else None

    def following_user_ids(self, viewer_users_id, candidate_uids: list) -> set:
        return {
            row[0]
            for row in self.db.query(UserConnection.following_id)
            .filter(
                UserConnection.follower_id == viewer_users_id,
                UserConnection.following_id.in_(candidate_uids),
            )
            .all()
        }

    def followed_profile_ids(self, viewer_users_id) -> list[int]:
        return [
            row[0]
            for row in self.db.query(Profile.id)
            .join(UserConnection, UserConnection.following_id == Profile.users_id)
            .filter(UserConnection.follower_id == viewer_users_id)
            .all()
        ]

    # -- posts -----------------------------------------------------------------

    def get_post(self, post_id: int) -> Optional[Post]:
        return self.db.query(Post).filter(Post.id == post_id).first()

    def get_active_post(self, post_id: int) -> Optional[Post]:
        return (
            self.db.query(Post)
            .filter(Post.id == post_id, Post.profile_id.in_(self.active_profile_ids()))
            .first()
        )

    def list_active_posts(self, limit: int, offset: int) -> list[Post]:
        return (
            self.db.query(Post)
            .options(selectinload(Post.deal_details))
            .filter(Post.profile_id.in_(self.active_profile_ids()))
            .order_by(Post.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

    def list_my_posts(self, profile_id: int, cursor_post_id: int | None, limit: int) -> list[Post]:
        query = (
            self.db.query(Post)
            .options(selectinload(Post.deal_details))
            .filter(Post.profile_id == profile_id)
        )
        if cursor_post_id is not None:
            query = query.filter(Post.id < cursor_post_id)
        return query.order_by(Post.id.desc()).limit(limit).all()

    def list_following_posts(
        self, followed_profile_ids: list[int], cutoff: datetime, seen_ids: set
    ) -> list[Post]:
        query = (
            self.db.query(Post)
            .options(selectinload(Post.deal_details))
            .filter(
                Post.profile_id.in_(followed_profile_ids),
                Post.created_at >= cutoff,
            )
        )
        if seen_ids:
            query = query.filter(Post.id.notin_(seen_ids))
        return query.all()

    def has_seen_recent_followed_post(
        self, followed_profile_ids: list[int], cutoff: datetime, seen_ids: set
    ) -> bool:
        return self.db.query(Post.id).filter(
            Post.profile_id.in_(followed_profile_ids),
            Post.created_at >= cutoff,
            Post.id.in_(seen_ids),
        ).first() is not None

    def increment_view_count(self, post_id: int) -> bool:
        """True if the view was counted; False on a duplicate (caller logs a revisit)."""
        try:
            self.db.query(Post).filter(Post.id == post_id).update(
                {Post.view_count: Post.view_count + 1},
                synchronize_session=False,
            )
            self.db.commit()
            return True
        except IntegrityError:
            self.db.rollback()
            return False

    def get_posts_by_ids(self, post_ids: list[int]) -> list[Post]:
        return (
            self.db.query(Post)
            .options(selectinload(Post.deal_details))
            .filter(Post.id.in_(post_ids))
            .all()
        )

    def increment_view_count_no_commit(self, post_id: int) -> None:
        self.db.query(Post).filter(Post.id == post_id).update(
            {Post.view_count: Post.view_count + 1},
            synchronize_session=False,
        )

    def record_first_view(self, post_id: int, profile_id: int) -> bool:
        self.db.add(PostView(post_id=post_id, profile_id=profile_id))
        try:
            self.db.flush()
        except IntegrityError:
            # Unique constraint on (post_id, profile_id) — already seen.
            self.db.rollback()
            return False
        self.increment_view_count_no_commit(post_id)
        self.db.commit()
        return True

    # -- likes / saves ---------------------------------------------------------

    def is_liked(self, post_id: int, profile_id: int) -> bool:
        return self.db.query(PostLike).filter(
            PostLike.post_id == post_id,
            PostLike.profile_id == profile_id,
        ).first() is not None

    def is_saved(self, post_id: int, profile_id: int) -> bool:
        return self.db.query(PostSave).filter(
            PostSave.post_id == post_id,
            PostSave.profile_id == profile_id,
        ).first() is not None

    def liked_post_ids(self, profile_id: int, post_ids: list[int]) -> set:
        return {
            row[0]
            for row in self.db.query(PostLike.post_id)
            .filter(PostLike.profile_id == profile_id, PostLike.post_id.in_(post_ids))
            .all()
        }

    def saved_post_ids(self, profile_id: int, post_ids: list[int]) -> set:
        return {
            row[0]
            for row in self.db.query(PostSave.post_id)
            .filter(PostSave.profile_id == profile_id, PostSave.post_id.in_(post_ids))
            .all()
        }

    def get_like(self, post_id: int, profile_id: int) -> Optional[PostLike]:
        return self.db.query(PostLike).filter(
            PostLike.post_id == post_id, PostLike.profile_id == profile_id
        ).first()

    def get_save(self, post_id: int, profile_id: int) -> Optional[PostSave]:
        return self.db.query(PostSave).filter(
            PostSave.post_id == post_id, PostSave.profile_id == profile_id
        ).first()

    def list_saves(self, profile_id: int, cursor_save_id: int | None, limit: int) -> list[PostSave]:
        query = self.db.query(PostSave).filter(PostSave.profile_id == profile_id)
        if cursor_save_id is not None:
            query = query.filter(PostSave.id < cursor_save_id)
        return query.order_by(PostSave.id.desc()).limit(limit).all()

    def bump_counter(self, post_id: int, column: str, delta: int) -> None:
        """Increment/decrement a denormalised counter on posts, no commit."""
        col = getattr(Post, column)
        self.db.query(Post).filter(Post.id == post_id).update(
            {col: col + delta}, synchronize_session=False
        )

    def get_profile_with_business_by_id(self, profile_id: int):
        return (
            self.db.query(Profile)
            .options(selectinload(Profile.business))
            .filter(Profile.id == profile_id)
            .first()
        )

    def get_commenters_with_business(self, profile_ids: list[int]) -> dict:
        return {
            p.id: p
            for p in self.db.query(Profile)
            .options(selectinload(Profile.business))
            .filter(Profile.id.in_(profile_ids))
            .all()
        }

    def list_comments_asc(self, post_id: int, cursor_comment_id: int | None, limit: int):
        query = self.db.query(PostComment).filter(PostComment.post_id == post_id)
        if cursor_comment_id is not None:
            query = query.filter(PostComment.id > cursor_comment_id)
        return query.order_by(PostComment.id.asc()).limit(limit).all()

    def get_comment_on_post(self, post_id: int, comment_id: int):
        return self.db.query(PostComment).filter(
            PostComment.id == comment_id,
            PostComment.post_id == post_id,
        ).first()

    # -- comments --------------------------------------------------------------

    def get_comment(self, comment_id: int) -> Optional[PostComment]:
        return self.db.query(PostComment).filter(PostComment.id == comment_id).first()

    def list_comments(self, post_id: int, cursor_id: int | None, limit: int) -> list[PostComment]:
        query = self.db.query(PostComment).filter(PostComment.post_id == post_id)
        if cursor_id is not None:
            query = query.filter(PostComment.id < cursor_id)
        return query.order_by(PostComment.id.desc()).limit(limit).all()

    # -- taste / seen ----------------------------------------------------------

    def get_category_taste_weights(self, profile_id: int, role_id: int | None) -> dict[str, float]:
        from app.modules.post.recommendation.session_taste import taste_service

        return taste_service.get_taste_weights(self.db, profile_id, "category", role_id)

    def upsert_post_embedding(
        self,
        post_id: int,
        vector: list,
        category: str,
        commodity_idx: int,
        expires_at,
        now,
        partition: str = "hot",
    ) -> None:
        from app.modules.post.recommendation.models import PostEmbedding

        existing = (
            self.db.query(PostEmbedding)
            .filter(PostEmbedding.post_id == post_id)
            .first()
        )
        if existing:
            existing.vector = vector
            existing.partition = partition
            existing.is_active = True
            existing.expires_at = expires_at
            existing.category = category
            existing.commodity_idx = commodity_idx
            existing.created_at = now
            return
        self.db.add(PostEmbedding(
            post_id=post_id,
            vector=vector,
            partition=partition,
            is_active=True,
            expires_at=expires_at,
            category=category,
            commodity_idx=commodity_idx,
            created_at=now,
        ))

    def deactivate_post_embedding(self, post_id: int) -> None:
        from app.modules.post.recommendation.models import PostEmbedding

        emb = (
            self.db.query(PostEmbedding)
            .filter(PostEmbedding.post_id == post_id)
            .first()
        )
        if emb:
            emb.is_active = False

    def seen_post_ids(self, profile_id: int) -> set:
        return {
            row[0]
            for row in self.db.query(SeenPost.post_id)
            .filter(SeenPost.profile_id == profile_id)
            .all()
        }
