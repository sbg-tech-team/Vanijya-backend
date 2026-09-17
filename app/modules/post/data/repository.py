"""SQLAlchemy implementation of IPostRepository.

The only file in the post module that touches the database. Query bodies,
eager-load strategies (selectinload vs joinedload), ordering, cursor filters
and the duplicate-view IntegrityError handling are moved verbatim from the
use-case files.

Transaction control stays with the caller where the use cases own multi-step
writes, so add/delete/commit/flush/refresh/rollback are exposed directly.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.modules.connections.data.models import UserConnection
from app.modules.post.data.models import Post, PostComment, PostLike, PostSave, PostView
from app.modules.post.data.recommendation_models import SeenPost
from app.modules.post.domain.interfaces.repository import IPostRepository
from app.modules.post.data.recommendation_models import PopularPost, PostEmbedding
from app.modules.post.recommendation.constants import (
    CATEGORY_EXPIRY_DAYS,
    COLD_MAX_HOURS,
    HOT_MAX_HOURS,
    PARTITION_ALLOWED,
    POPULAR_LIMIT,
    WARM_MAX_HOURS,
)
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

    def all_followed_user_ids(self, viewer_users_id) -> set:
        rows = (
            self.db.query(UserConnection.following_id)
            .filter(UserConnection.follower_id == viewer_users_id)
            .all()
        )
        return {r[0] for r in rows}

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
        from app.modules.post.data.recommendation_models import PostEmbedding

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
        from app.modules.post.data.recommendation_models import PostEmbedding

        emb = (
            self.db.query(PostEmbedding)
            .filter(PostEmbedding.post_id == post_id)
            .first()
        )
        if emb:
            emb.is_active = False

    # ── Recommendation reads ─────────────────────────────────────────────────
    # The ranking maths lives in post/recommendation/engine.py; the SQL lives
    # here, so the engine can be driven with a fake repository and the data
    # layer stays the only place that talks to the database.

    def ann_post_candidates(
        self, vector: str, partition: str, limit: int, exclude_ids: set
    ) -> list[dict]:
        from app.modules.post.recommendation.engine import _parse_vec

        exclude_clause = (
            f"AND post_id NOT IN ({','.join(str(int(i)) for i in exclude_ids)})"
            if exclude_ids else ""
        )
        rows = self.db.execute(
            text(f"""
                SELECT post_id, category, vector
                FROM post_embeddings
                WHERE partition = :partition
                  AND is_active = true
                  {exclude_clause}
                ORDER BY vector <=> CAST(:vec AS vector)
                LIMIT :limit
            """),
            {"vec": vector, "partition": partition, "limit": limit},
        ).mappings().all()
        return [
            {"post_id": r["post_id"], "category": r["category"],
             "vector": _parse_vec(r["vector"])}
            for r in rows
        ]

    def fresh_post_candidates(
        self, cutoff, limit: int, commodity_idxs: set, exclude_ids: set
    ) -> list[dict]:
        from app.modules.post.recommendation.engine import _parse_vec

        exclude_clause = (
            f"AND pe.post_id NOT IN ({','.join(str(int(i)) for i in exclude_ids)})"
            if exclude_ids else ""
        )
        commodity_clause = (
            f"AND pe.commodity_idx IN ({','.join(str(int(i)) for i in commodity_idxs)})"
            if commodity_idxs else ""
        )
        rows = self.db.execute(
            text(f"""
                SELECT pe.post_id, pe.category, pe.vector, p.target_roles
                FROM post_embeddings pe
                JOIN posts p ON p.id = pe.post_id
                WHERE pe.is_active = true
                  AND p.created_at >= :cutoff
                  AND p.is_public = true
                  {commodity_clause}
                  {exclude_clause}
                ORDER BY p.created_at DESC
                LIMIT :limit
            """),
            {"cutoff": cutoff, "limit": limit},
        ).mappings().all()
        return [
            {"post_id": r["post_id"], "category": r["category"],
             "vector": _parse_vec(r["vector"]), "target_roles": r["target_roles"]}
            for r in rows
        ]

    def popular_post_candidates(
        self, commodity_idxs: set, exclude_ids: set, limit: int
    ) -> list:
        from app.modules.post.data.recommendation_models import PopularPost

        q = self.db.query(PopularPost).filter(
            PopularPost.commodity_idx.in_(list(commodity_idxs))
        )
        if exclude_ids:
            q = q.filter(~PopularPost.post_id.in_(list(exclude_ids)))
        return q.order_by(PopularPost.velocity_score.desc()).limit(limit).all()

    def record_seen_posts(self, profile_id: int, post_ids: list[int]) -> None:
        from app.modules.post.data.recommendation_models import SeenPost

        now = datetime.now(timezone.utc)
        for pid in post_ids:
            self.db.add(SeenPost(profile_id=profile_id, post_id=pid, seen_at=now))
        try:
            self.db.commit()
        except IntegrityError:
            # Already seen — the unique constraint is the dedup, and re-seeing a
            # post is not an error worth failing the caller for.
            self.db.rollback()

    def seen_post_ids_since(self, profile_id: int, cutoff) -> set:
        from app.modules.post.data.recommendation_models import SeenPost

        rows = (
            self.db.query(SeenPost.post_id)
            .filter(SeenPost.profile_id == profile_id, SeenPost.seen_at >= cutoff)
            .all()
        )
        return {r[0] for r in rows}

    def user_post_feed_vector(self, users_id):
        from app.modules.profile.data.models import UserEmbedding

        row = (
            self.db.query(UserEmbedding)
            .filter(UserEmbedding.user_id == users_id)
            .first()
        )
        return row.post_feed_vector if row else None


    # ── Recommendation maintenance (batch) ───────────────────────────────────
    # Bulk partition demotion and the popular-posts rebuild. Both are pure data
    # operations; the job functions that used to hold this SQL are now thin
    # wrappers so the scheduler can keep calling them.

    def run_embedding_expiry(self) -> dict:
        now = datetime.now(timezone.utc)

        expired = (
            self.db.query(PostEmbedding)
            .filter(PostEmbedding.is_active == True, PostEmbedding.expires_at <= now)
            .all()
        )
        for emb in expired:
            emb.is_active = False

        expired_ids = {emb.post_id for emb in expired}
        if expired_ids:
            self.db.query(PopularPost).filter(
                PopularPost.post_id.in_(expired_ids)
            ).delete(synchronize_session=False)

        hot_cutoff = now - timedelta(hours=HOT_MAX_HOURS)
        warm_allowed = list(PARTITION_ALLOWED["warm"])
        to_warm = (
            self.db.query(PostEmbedding)
            .filter(
                PostEmbedding.partition == "hot",
                PostEmbedding.is_active == True,
                PostEmbedding.created_at <= hot_cutoff,
                PostEmbedding.category.in_(warm_allowed),
            )
            .all()
        )
        for emb in to_warm:
            emb.partition = "warm"

        warm_cutoff = now - timedelta(hours=WARM_MAX_HOURS)
        cold_allowed = list(PARTITION_ALLOWED["cold"])
        to_cold = (
            self.db.query(PostEmbedding)
            .filter(
                PostEmbedding.partition == "warm",
                PostEmbedding.is_active == True,
                PostEmbedding.created_at <= warm_cutoff,
                PostEmbedding.category.in_(cold_allowed),
            )
            .all()
        )
        for emb in to_cold:
            emb.partition = "cold"

        deleted = (
            self.db.query(PostEmbedding)
            .filter(
                PostEmbedding.partition == "cold",
                PostEmbedding.created_at <= now - timedelta(hours=COLD_MAX_HOURS),
            )
            .delete(synchronize_session=False)
        )

        self.db.commit()
        return {
            "soft_expired": len(expired),
            "migrated_to_warm": len(to_warm),
            "migrated_to_cold": len(to_cold),
            "hard_deleted": deleted,
        }

    def rebuild_popular_posts(self) -> dict:
        now = datetime.now(timezone.utc)
        lookback = now - timedelta(days=30)

        active_post_ids = {
            row[0]
            for row in self.db.query(PostEmbedding.post_id)
            .filter(PostEmbedding.is_active == True)
            .all()
        }

        posts = (
            self.db.query(Post)
            .filter(Post.created_at >= lookback, Post.id.in_(active_post_ids))
            .all()
        )

        scored: list[tuple[int, float]] = []
        for post in posts:
            created = post.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            hours = max((now - created).total_seconds() / 3600, 0.0)
            saves = getattr(post, "save_count", 0)
            velocity = (saves * 3 + post.comment_count * 2 + post.like_count) / ((hours + 1) ** 1.5)
            scored.append((post.id, velocity))

        scored.sort(key=lambda x: x[1], reverse=True)

        emb_map = {
            row[0]: row[1]
            for row in self.db.query(PostEmbedding.post_id, PostEmbedding.commodity_idx)
            .filter(PostEmbedding.post_id.in_([s[0] for s in scored]))
            .all()
        }
        cat_map = {
            row[0]: row[1]
            for row in self.db.query(PostEmbedding.post_id, PostEmbedding.category)
            .filter(PostEmbedding.post_id.in_([s[0] for s in scored]))
            .all()
        }

        per_commodity: dict[int, list] = {}
        for post_id, vel in scored:
            cidx = emb_map.get(post_id)
            if cidx is None:
                continue
            per_commodity.setdefault(cidx, []).append((post_id, vel))
        top_ids: set[int] = set()
        for cidx, entries in per_commodity.items():
            for post_id, _ in entries[:50]:
                top_ids.add(post_id)

        # Replace the entire popular_posts table in one shot:
        # delete-all then bulk-insert avoids ORM dirty-object race conditions
        # with the concurrent expiry_job which also deletes from popular_posts.
        self.db.query(PopularPost).delete(synchronize_session=False)

        post_map = {p.id: p for p in posts}
        new_rows = []
        for post_id, velocity in scored:
            if post_id not in top_ids:
                continue
            post = post_map.get(post_id)
            if not post:
                continue

            created = post.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            hours = max((now - created).total_seconds() / 3600, 0.0)
            saves = getattr(post, "save_count", 0)

            new_rows.append(PopularPost(
                post_id=post_id,
                commodity_idx=emb_map.get(post_id, 0),
                category=cat_map.get(post_id, "other"),
                velocity_score=velocity,
                saves_count=saves,
                likes_count=post.like_count,
                comments_count=post.comment_count,
                hours_since_post=hours,
                last_updated_at=now,
                is_active=True,
            ))

        self.db.bulk_save_objects(new_rows)
        self.db.commit()
        return {"synced": len(new_rows), "top_ids_count": len(top_ids)}

    def seen_post_ids(self, profile_id: int) -> set:
        return {
            row[0]
            for row in self.db.query(SeenPost.post_id)
            .filter(SeenPost.profile_id == profile_id)
            .all()
        }
