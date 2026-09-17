"""SQL for the post taste store. Implements ITasteRepository.

Every statement here was lifted verbatim from
post/recommendation/session_taste/, which mixed this SQL with the scoring maths
in a folder outside the layer structure. The maths stayed there; only the
database access moved.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.recommendation.lookup import AmplifyLookupMixin
from app.modules.post.data.models import Post
from app.modules.post.data.taste_models import PostInteractionEvent, UserPostTaste
from app.modules.post.domain.interfaces.taste_repository import ITasteRepository
from app.modules.profile.data.models import Business, Profile

_ENGAGED_EVENTS = ("dwell", "open_read_more", "open_carousel", "open_comments", "revisit")


class TasteRepository(AmplifyLookupMixin, ITasteRepository):
    def __init__(self, db: Session):
        self.db = db


    def commit(self) -> None:
        self.db.commit()

    # ── Taste rows ───────────────────────────────────────────────────────────

    def upsert_taste(
        self, profile_id: int, dimension_type: str, dimension_key: str,
        positive_delta: float, negative_delta: float = 0.0, event_count: int = 1,
    ) -> None:
        now = datetime.now(timezone.utc)
        stmt = (
            pg_insert(UserPostTaste.__table__)
            .values(
                profile_id=profile_id,
                dimension_type=dimension_type,
                dimension_key=dimension_key,
                positive_score=positive_delta,
                negative_score=negative_delta,
                event_count=event_count,
                last_event_at=now,
            )
            .on_conflict_do_update(
                index_elements=["profile_id", "dimension_type", "dimension_key"],
                set_={
                    "positive_score": UserPostTaste.__table__.c.positive_score + positive_delta,
                    "negative_score": UserPostTaste.__table__.c.negative_score + negative_delta,
                    "event_count": UserPostTaste.__table__.c.event_count + event_count,
                    "last_event_at": now,
                },
            )
        )
        self.db.execute(stmt)

    def taste_rows(self, profile_id: int, dimension_types: tuple[str, ...]) -> list:
        return (
            self.db.query(UserPostTaste)
            .filter(
                UserPostTaste.profile_id == profile_id,
                UserPostTaste.dimension_type.in_(dimension_types),
            )
            .all()
        )

    def seed_taste_rows(self, profile_id: int, category_scores: dict) -> None:
        now = datetime.now(timezone.utc)
        for category, default_count in category_scores.items():
            self.db.execute(
                pg_insert(UserPostTaste.__table__)
                .values(
                    profile_id=profile_id,
                    dimension_type="category",
                    dimension_key=category,
                    positive_score=float(default_count),
                    negative_score=0.0,
                    event_count=0,
                    last_event_at=now,
                )
                .on_conflict_do_nothing()
            )
        self.db.commit()

    # ── Interaction events ───────────────────────────────────────────────────

    def add_interaction_events(self, events: list) -> None:
        for e in events:
            self.db.add(e)

    def unprocessed_events(self, event_types: tuple[str, ...], limit: int) -> list:
        return (
            self.db.query(PostInteractionEvent)
            .filter(
                PostInteractionEvent.event_type.in_(event_types),
                PostInteractionEvent.processed_at.is_(None),
            )
            .order_by(PostInteractionEvent.id)
            .limit(limit)
            .all()
        )

    def mark_events_processed(self, event_ids: list[int], now) -> None:
        if not event_ids:
            return
        self.db.query(PostInteractionEvent).filter(
            PostInteractionEvent.id.in_(event_ids)
        ).update({"processed_at": now}, synchronize_session=False)

    def repeated_ignore_pairs(self, threshold: int, limit: int) -> list:
        engaged = ", ".join(f"'{e}'" for e in _ENGAGED_EVENTS)
        rows = self.db.execute(
            text(f"""
                SELECT profile_id, post_id
                FROM post_interaction_events
                GROUP BY profile_id, post_id
                HAVING
                    SUM(CASE WHEN event_type = 'impression' THEN 1 ELSE 0 END)
                        >= :threshold
                    AND SUM(CASE WHEN event_type IN ({engaged}) THEN 1 ELSE 0 END) = 0
                    AND SUM(CASE WHEN event_type = 'impression'
                                 AND processed_at IS NULL THEN 1 ELSE 0 END) > 0
                ORDER BY profile_id, post_id
                LIMIT :limit
            """),
            {"threshold": threshold, "limit": limit},
        ).mappings().all()
        return [(r["profile_id"], r["post_id"]) for r in rows]

    def mark_impressions_processed(self, pairs: list, now) -> None:
        if not pairs:
            return
        pairs_str = ", ".join(f"({int(p)}, {int(q)})" for p, q in pairs)
        self.db.execute(
            text(f"""
                UPDATE post_interaction_events
                SET processed_at = :now
                WHERE event_type = 'impression'
                  AND processed_at IS NULL
                  AND (profile_id, post_id) IN ({pairs_str})
            """),
            {"now": now},
        )

    # ── Post metadata ────────────────────────────────────────────────────────

    def post_taste_meta(self, post_ids: list[int]) -> dict:
        rows = (
            self.db.query(Post.id, Post.category_id, Post.commodity_id,
                          Business.city, Business.state)
            .outerjoin(Business, Business.profile_id == Post.profile_id)
            .filter(Post.id.in_(post_ids))
            .all()
        )
        return {r[0]: (r[1], r[2], r[3], r[4]) for r in rows}

    def post_author_meta(self, post_ids: list[int]) -> dict:
        rows = (
            self.db.query(Post.id, Post.category_id, Post.commodity_id, Post.profile_id)
            .filter(Post.id.in_(post_ids))
            .all()
        )
        return {r[0]: (r[1], r[2], r[3]) for r in rows}

    def bulk_add_events(self, rows: list) -> None:
        self.db.bulk_save_objects(rows)

    def mark_posts_seen(self, profile_id: int, post_ids: list[int], now) -> None:
        self.db.execute(
            text("""
                INSERT INTO seen_posts (profile_id, post_id, seen_at)
                SELECT :profile_id, unnest(CAST(:post_ids AS int[])), :seen_at
                ON CONFLICT (profile_id, post_id) DO NOTHING
            """),
            {
                "profile_id": profile_id,
                "post_ids": "{" + ",".join(str(int(p)) for p in post_ids) + "}",
                "seen_at": now,
            },
        )

    def get_post_for_taste(self, post_id: int):
        return self.db.query(Post).filter(Post.id == post_id).first()

    def rollback(self) -> None:
        self.db.rollback()

    def profile_exists(self, profile_id: int) -> bool:
        return self.db.query(Profile.id).filter(Profile.id == profile_id).first() is not None
