"""
Post Recommendation Service

Write path  – index_post():            called by post service on publish
Read path   – get_recommended_posts(): returns personalised feed cards
Taste path  – taste_service.get_taste_weights() (post_user_interaction)
"""
import math
from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.modules.post.post_recommendation_module.constants import (
    CATEGORY_NAMES, CATEGORY_EXPIRY_DAYS, COMMODITY_ID_TO_IDX,
    FEED_SIZE, FETCH_TARGET,
    FRESH_BOOST_PEAK, FRESH_DECAY_TAU, FRESH_INJECT_HOURS, FRESH_SLOTS,
    MAX_PER_AUTHOR, MAX_PER_CATEGORY, MIN_POOL_SIZE, POPULAR_LIMIT,
)
from app.modules.post.post_recommendation_module.models import (
    PostEmbedding, PopularPost, SeenPost,
)
from app.modules.post.post_user_interaction import taste_service
from app.modules.post.post_recommendation_module.vector import (
    build_post_vector,
    build_user_feed_vector,
    weighted_cosine_similarity,
)
from app.modules.profile.models import Profile
from app.modules.connections.models import UserConnection


def _parse_vec(v) -> list[float]:
    """
    Normalise a pgvector column value to list[float].
    Raw text() SQL queries bypass the ORM type codec, so pgvector returns the
    vector as a string '[v1,v2,...]' instead of a Python list. This handles
    both the string case and the numpy-array case (when the codec is active).
    """
    if isinstance(v, str):
        return [float(x) for x in v.strip("[]").split(",")]
    if hasattr(v, "tolist"):   # numpy array
        return v.tolist()
    return list(v)


# ---------------------------------------------------------------------------
# Write path: index post on publish --> on any post create/update embedding and set partition to 'hot'
# ---------------------------------------------------------------------------

def index_post(
    db: Session,
    post_id: int,
    commodity_id: int,
    target_role_ids: list[int] | None,
    lat: float,
    lon: float,
    category_id: int,
    commodity_quantity: float | None = None,
) -> None:
    category = CATEGORY_NAMES[category_id]
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=CATEGORY_EXPIRY_DAYS[category])
    commodity_idx = COMMODITY_ID_TO_IDX.get(commodity_id, 0)
    is_deal = (category == "deal_req")

    vector = build_post_vector(
        commodity_id=commodity_id,
        target_role_ids=target_role_ids,
        lat=lat,
        lon=lon,
        is_deal=is_deal,
        commodity_quantity=commodity_quantity,
    )

    existing = db.query(PostEmbedding).filter(PostEmbedding.post_id == post_id).first()
    if existing:
        existing.vector = vector
        existing.partition = "hot"
        existing.is_active = True
        existing.expires_at = expires_at
        existing.category = category
        existing.commodity_idx = commodity_idx
        existing.created_at = now
    else:
        db.add(PostEmbedding(
            post_id=post_id,
            vector=vector,
            partition="hot",
            is_active=True,
            expires_at=expires_at,
            category=category,
            commodity_idx=commodity_idx,
            created_at=now,
        ))
    db.commit()


# ---------------------------------------------------------------------------
# Write path: remove post from index on delete --> set is_active to False  
# ---------------------------------------------------------------------------

def remove_post_index(db: Session, post_id: int) -> None:
    emb = db.query(PostEmbedding).filter(PostEmbedding.post_id == post_id).first()
    if emb:
        emb.is_active = False
        db.commit()


# ---------------------------------------------------------------------------
# Taste path: record_interaction and get_taste_for_feed have moved to
# app.modules.post.post_user_interaction.service
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Internal helpers for the read path
# ---------------------------------------------------------------------------



def _seen_post_ids(db: Session, profile_id: int) -> set[int]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    rows = (
        db.query(SeenPost.post_id)
        .filter(SeenPost.profile_id == profile_id, SeenPost.seen_at >= cutoff)
        .all()
    )
    return {r[0] for r in rows}


def record_seen(db: Session, profile_id: int, post_ids: list[int]) -> None:
    """Record posts as seen. Called by the client-driven /seen endpoint and on explicit post open."""
    now = datetime.now(timezone.utc)
    for pid in post_ids:
        db.add(SeenPost(profile_id=profile_id, post_id=pid, seen_at=now))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()

# ---------------------------------------------------------------------------
# ANN pre-filter: fetch candidates from the most relevant partition(s) using HNSW vector search
def _query_partition(
    db: Session, partition: str, limit: int, exclude_ids: set[int], user_vec: list[float]
) -> list[dict]:
    """
    HNSW ANN pre-filter: fetches the most relevant posts in a partition
    ordered by approximate cosine distance. Returns raw vectors so the
    caller can apply exact weighted_cosine_similarity for the final vec_score.
    """
    # convert user_vec list[float] to Postgres array literal format: '[v1,v2,...]'
    vec_str = "[" + ",".join(str(v) for v in user_vec) + "]"

    # exclude_ids takes set pool_exclude which is seeded with seen post_ids "and expanded with already fetched candidates as we query multiple partitions. This ensures we don't fetch the same post multiple times across hot/warm/cold."
    exclude_clause = (
        f"AND post_id NOT IN ({','.join(str(i) for i in exclude_ids)})"
        if exclude_ids else ""
    )

    # <=> is cosine distance operator provided by pgvector.
    # :partition is as asked in get_recommended_posts() and determines the freshness bucket (hot/warm/cold).
    rows = db.execute(
        text(f"""
            SELECT post_id, category, vector
            FROM post_embeddings
            WHERE partition = :partition
              AND is_active = true
              {exclude_clause}
            ORDER BY vector <=> CAST(:vec AS vector)
            LIMIT :limit
        """),
        {"vec": vec_str, "partition": partition, "limit": limit},
    ).mappings().all()

    return [
        {"post_id": r["post_id"], "category": r["category"], "vector": _parse_vec(r["vector"])}
        for r in rows
    ]


def _get_popular_posts(
    db: Session, commodity_idxs: set[int], exclude_ids: set[int]
) -> list[dict]:
    q = db.query(PopularPost).filter(
        PopularPost.commodity_idx.in_(list(commodity_idxs)),
        PopularPost.is_active == True,
    )
    if exclude_ids:
        q = q.filter(~PopularPost.post_id.in_(list(exclude_ids)))
    rows = q.order_by(PopularPost.velocity_score.desc()).limit(POPULAR_LIMIT).all()
    return [
        {"post_id": r.post_id, "category": r.category, "vec_score": 0.5}
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Reranking
# ---------------------------------------------------------------------------

def _category_weight(cat_weights: dict[str, float], category: str) -> float:
    total = sum(math.log1p(v) for v in cat_weights.values())
    if total == 0:
        return 1.0 / max(len(cat_weights), 1)
    return math.log1p(cat_weights.get(category, 0.05)) / total


def _commodity_multiplier(commodity_weights: dict[str, float], commodity_id: int | None) -> float:
    if not commodity_id or not commodity_weights:
        return 1.0
    score = commodity_weights.get(str(commodity_id), 0.0)
    if score <= 0:
        return 1.0
    max_score = max(commodity_weights.values())
    return 1.0 + 0.3 * min(score / max(max_score, 0.05), 1.0)


def _freshness(created_at: datetime) -> float:
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    age_h = max(0.0, (datetime.now(timezone.utc) - created_at).total_seconds() / 3600)
    return 1.0 + FRESH_BOOST_PEAK * math.exp(-age_h / FRESH_DECAY_TAU)


def _rerank(
    db: Session,
    candidates: list[dict],
    cat_weights: dict[str, float],
    commodity_weights: dict[str, float],
    author_weights: dict[str, float],
    followed_user_ids: set,
) -> list[dict]:
    from app.modules.post.models import Post

    if not candidates:
        return []

    post_ids = list({c["post_id"] for c in candidates})
    posts = {p.id: p for p in db.query(Post).filter(Post.id.in_(post_ids)).all()}

    profile_ids = list({p.profile_id for p in posts.values()})
    profiles = {
        p.id: p
        for p in db.query(Profile).filter(Profile.id.in_(profile_ids)).all()
    }

    scored: list[dict] = []
    for c in candidates:
        post = posts.get(c["post_id"])
        if not post:
            continue

        saves = getattr(post, "save_count", 0)
        raw_eng = saves * 3 + post.comment_count * 2 + post.like_count
        engagement = min(math.log1p(raw_eng) / 6.9, 1.0)

        author_profile = profiles.get(post.profile_id)
        author_user_id = author_profile.users_id if author_profile else None
        is_followed = author_user_id in followed_user_ids

        if is_followed:
            social = 1.5
        else:
            author_score = author_weights.get(str(post.profile_id), 0.0)
            social = taste_service.get_author_affinity(author_score)

        final = (
            c["vec_score"]
            * _category_weight(cat_weights, c["category"])
            * _commodity_multiplier(commodity_weights, post.commodity_id)
            * (1 + engagement)
            * _freshness(post.created_at)
            * social
        )

        scored.append({
            "post_id": post.id,
            "category": c["category"],
            "author_profile_id": post.profile_id,
            "final_score": round(final, 6),
        })

    scored.sort(key=lambda x: x["final_score"], reverse=True)
    return scored


def _apply_diversity(scored: list[dict], limit: int = FEED_SIZE) -> list[dict]:
    cat_counts: dict[str, int] = {}
    author_counts: dict[int, int] = {}
    result: list[dict] = []

    for item in scored:
        cat = item["category"]
        author = item["author_profile_id"]
        if cat_counts.get(cat, 0) >= MAX_PER_CATEGORY:
            continue
        if author_counts.get(author, 0) >= MAX_PER_AUTHOR:
            continue
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
        author_counts[author] = author_counts.get(author, 0) + 1
        result.append(item)
        if len(result) >= limit:
            break

    return result


_ROLE_NAMES = {1: "trader", 2: "broker", 3: "exporter"}


def _build_feed_cards(db: Session, final: list[dict], viewer_profile_id: int) -> list:
    from sqlalchemy import func
    from app.modules.post.models import Post, PostLike, PostSave, PostComment
    from app.modules.post.schemas import PostDealResponse
    from app.modules.post.post_recommendation_module.schemas import FeedPostCard

    if not final:
        return []

    post_ids = [f["post_id"] for f in final]
    posts = {p.id: p for p in db.query(Post).filter(Post.id.in_(post_ids)).all()}

    author_ids = list({p.profile_id for p in posts.values()})
    authors = {p.id: p for p in db.query(Profile).filter(Profile.id.in_(author_ids)).all()}

    liked_ids = {
        r[0] for r in db.query(PostLike.post_id).filter(
            PostLike.post_id.in_(post_ids),
            PostLike.profile_id == viewer_profile_id,
        ).all()
    }
    saved_ids = {
        r[0] for r in db.query(PostSave.post_id).filter(
            PostSave.post_id.in_(post_ids),
            PostSave.profile_id == viewer_profile_id,
        ).all()
    }

    # Latest comment per post — one query via max(id) per post_id
    latest_comment_subq = (
        db.query(PostComment.post_id, func.max(PostComment.id).label("max_id"))
        .filter(PostComment.post_id.in_(post_ids))
        .group_by(PostComment.post_id)
        .subquery()
    )
    latest_comments = {
        c.post_id: c
        for c in db.query(PostComment).join(
            latest_comment_subq, PostComment.id == latest_comment_subq.c.max_id
        ).all()
    }
    commenter_ids = list({c.profile_id for c in latest_comments.values()})
    commenters = (
        {p.id: p for p in db.query(Profile).filter(Profile.id.in_(commenter_ids)).all()}
        if commenter_ids else {}
    )

    cards = []
    for f in final:
        post = posts.get(f["post_id"])
        if not post:
            continue
        author = authors.get(post.profile_id)
        biz = author.business if author else None

        # location_name: post's own value OR author's "city, state"
        location_name = post.location_name
        if not location_name and biz:
            parts = [p for p in [biz.city, biz.state] if p]
            location_name = ", ".join(parts) or None

        latest = latest_comments.get(post.id)
        commenter = commenters.get(latest.profile_id) if latest else None

        cards.append(FeedPostCard(
            id=post.id,
            profile_id=post.profile_id,
            category_id=post.category_id,
            commodity_id=post.commodity_id,
            title=post.title,
            caption=post.caption,
            image_urls=post.image_urls,
            is_public=post.is_public,
            target_roles=post.target_roles,
            allow_comments=post.allow_comments,
            deal_details=PostDealResponse.model_validate(post.deal_details) if post.deal_details else None,
            source_url=post.source_url,
            location_name=location_name,
            latitude=post.latitude,
            longitude=post.longitude,
            view_count=post.view_count,
            like_count=post.like_count,
            comment_count=post.comment_count,
            share_count=post.share_count,
            save_count=post.save_count,
            is_liked=post.id in liked_ids,
            is_saved=post.id in saved_ids,
            created_at=post.created_at,
            author_name=author.name if author else "unknown",
            author_role=_ROLE_NAMES.get(author.role_id, "trader") if author else "trader",
            author_user_id=str(author.users_id) if author else "",
            author_company=biz.business_name if biz else None,
            author_avatar_url=author.avatar_url if author else None,
            is_user_verified=author.is_user_verified if author else False,
            is_business_verified=author.is_business_verified if author else False,
            comment_preview_author=commenter.name if commenter else None,
            comment_preview_text=latest.content if latest else None,
        ))

    return cards


# ---------------------------------------------------------------------------
# Fresh pool guarantee
# ---------------------------------------------------------------------------

def _ensure_fresh_in_pool(
    db: Session,
    viewer_role_id: int,
    commodity_idxs: set[int],
    exclude_ids: set[int],
    user_vec: list[float],
    limit: int,
) -> list[dict]:
    """
    Guarantees recently published posts enter the candidate pool even when the
    hot ANN search misses them (happens when > FETCH_TARGET hot posts exist and
    the new post's vector similarity is below the cutoff).

    Returns [{post_id, category, vec_score}] — same shape as ANN pool entries.
    These flow through _rerank and _apply_diversity unchanged; the continuous
    freshness boost in _freshness() provides their exposure lift.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=FRESH_INJECT_HOURS)

    exclude_clause = (
        f"AND pe.post_id NOT IN ({','.join(str(i) for i in exclude_ids)})"
        if exclude_ids else ""
    )
    commodity_clause = (
        f"AND pe.commodity_idx IN ({','.join(str(i) for i in commodity_idxs)})"
        if commodity_idxs else ""
    )

    rows = db.execute(
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
        {"cutoff": cutoff, "limit": limit * 3},
    ).mappings().all()

    result = []
    for r in rows:
        target = r["target_roles"]
        if target and viewer_role_id not in target:
            continue
        vec_score = weighted_cosine_similarity(user_vec, _parse_vec(r["vector"]))
        result.append({
            "post_id": r["post_id"],
            "category": r["category"],
            "vec_score": vec_score,
        })
        if len(result) >= limit:
            break

    return result


# ---------------------------------------------------------------------------
# Main read path
# ---------------------------------------------------------------------------

def get_recommended_posts(db: Session, profile_id: int, limit: int = FEED_SIZE) -> list:
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        raise ValueError(f"Profile {profile_id} not found")

    commodity_ids = [pc.commodity_id for pc in profile.commodities]
    commodity_idxs = {
        COMMODITY_ID_TO_IDX[cid] for cid in commodity_ids if cid in COMMODITY_ID_TO_IDX
    }

    from app.modules.profile.models import UserEmbedding
    emb_row = db.query(UserEmbedding).filter(
        UserEmbedding.user_id == profile.users_id
    ).first()

    if emb_row and emb_row.post_feed_vector is not None:
        user_vec = _parse_vec(emb_row.post_feed_vector)
    else:
        user_vec = build_user_feed_vector(
            commodity_ids=commodity_ids,
            role_id=profile.role_id,
            lat=float(profile.business.latitude),
            lon=float(profile.business.longitude),
            commodity_quantity=(float(profile.quantity_min) + float(profile.quantity_max)) / 2,
        )

    cat_weights       = taste_service.get_taste_weights(db, profile_id, "category", profile.role_id)
    commodity_weights = taste_service.get_taste_weights(db, profile_id, "commodity")
    author_weights    = taste_service.get_taste_weights(db, profile_id, "author")

    followed_user_ids = {
        row.following_id
        for row in db.query(UserConnection.following_id)
        .filter(UserConnection.follower_id == profile.users_id)
        .all()
    }

    seen_ids = _seen_post_ids(db, profile_id)
    pool_exclude: set[int] = set(seen_ids)
    pool: list[dict] = []

    hot_embs = _query_partition(db, "hot", FETCH_TARGET, pool_exclude, user_vec)
    for emb in hot_embs:
        score = weighted_cosine_similarity(user_vec, emb["vector"])
        pool.append({"post_id": emb["post_id"], "category": emb["category"], "vec_score": score})
        pool_exclude.add(emb["post_id"])

    if len(pool) < MIN_POOL_SIZE:
        warm_embs = _query_partition(db, "warm", FETCH_TARGET - len(pool), pool_exclude, user_vec)
        for emb in warm_embs:
            score = weighted_cosine_similarity(user_vec, emb["vector"])
            pool.append({"post_id": emb["post_id"], "category": emb["category"], "vec_score": score})
            pool_exclude.add(emb["post_id"])

    if len(pool) < MIN_POOL_SIZE:
        cold_embs = _query_partition(db, "cold", FETCH_TARGET - len(pool), pool_exclude, user_vec)
        for emb in cold_embs:
            score = weighted_cosine_similarity(user_vec, emb["vector"])
            pool.append({"post_id": emb["post_id"], "category": emb["category"], "vec_score": score})
            pool_exclude.add(emb["post_id"])

    popular = _get_popular_posts(db, commodity_idxs or {0, 1, 2}, pool_exclude)
    pool.extend(popular)
    for p in popular:
        pool_exclude.add(p["post_id"])

    # Guarantee fresh posts are in the pool even if the hot ANN missed them.
    # They enter with their actual vec_score and compete via score + freshness boost.
    fresh = _ensure_fresh_in_pool(
        db=db,
        viewer_role_id=profile.role_id,
        commodity_idxs=commodity_idxs or {0, 1, 2},
        exclude_ids=pool_exclude,
        user_vec=user_vec,
        limit=FRESH_SLOTS,
    )
    pool.extend(fresh)

    scored = _rerank(db, pool, cat_weights, commodity_weights, author_weights, followed_user_ids)
    final = _apply_diversity(scored, limit=limit)

    return _build_feed_cards(db, final, profile_id)
