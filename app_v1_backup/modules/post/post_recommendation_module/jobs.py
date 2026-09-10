"""
Background jobs for the post recommendation engine.

run_expiry_job()         – runs every hour
run_popular_posts_sync() – runs every 15 minutes
"""
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from app.modules.post.post_recommendation_module.constants import (
    HOT_MAX_HOURS,
    WARM_MAX_HOURS,
    COLD_MAX_HOURS,
    PARTITION_ALLOWED,
)
from app.modules.post.post_recommendation_module.models import PostEmbedding, PopularPost
from app.modules.post.models import Post


def run_expiry_job(db: Session) -> dict:
    now = datetime.now(timezone.utc)

    expired = (
        db.query(PostEmbedding)
        .filter(PostEmbedding.is_active == True, PostEmbedding.expires_at <= now)
        .all()
    )
    for emb in expired:
        emb.is_active = False

    expired_ids = {emb.post_id for emb in expired}
    if expired_ids:
        db.query(PopularPost).filter(
            PopularPost.post_id.in_(expired_ids)
        ).delete(synchronize_session=False)

    hot_cutoff = now - timedelta(hours=HOT_MAX_HOURS)
    warm_allowed = list(PARTITION_ALLOWED["warm"])
    to_warm = (
        db.query(PostEmbedding)
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
        db.query(PostEmbedding)
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
        db.query(PostEmbedding)
        .filter(
            PostEmbedding.partition == "cold",
            PostEmbedding.created_at <= now - timedelta(hours=COLD_MAX_HOURS),
        )
        .delete(synchronize_session=False)
    )

    db.commit()
    return {
        "soft_expired": len(expired),
        "migrated_to_warm": len(to_warm),
        "migrated_to_cold": len(to_cold),
        "hard_deleted": deleted,
    }


def run_popular_posts_sync(db: Session) -> dict:
    now = datetime.now(timezone.utc)
    lookback = now - timedelta(days=30)

    active_post_ids = {
        row[0]
        for row in db.query(PostEmbedding.post_id)
        .filter(PostEmbedding.is_active == True)
        .all()
    }

    posts = (
        db.query(Post)
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
        for row in db.query(PostEmbedding.post_id, PostEmbedding.commodity_idx)
        .filter(PostEmbedding.post_id.in_([s[0] for s in scored]))
        .all()
    }
    cat_map = {
        row[0]: row[1]
        for row in db.query(PostEmbedding.post_id, PostEmbedding.category)
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
    db.query(PopularPost).delete(synchronize_session=False)

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

    db.bulk_save_objects(new_rows)
    db.commit()
    return {"synced": len(new_rows), "top_ids_count": len(top_ids)}
