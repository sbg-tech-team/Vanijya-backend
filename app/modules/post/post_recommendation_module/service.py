"""
Post Recommendation Service

Write path  – index_post():         called by post service on publish
Read path   – get_recommended():    returns list[{post_id, score}] for the feed
Taste path  – record_interaction(): called by post service on every engagement
"""
import math
from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.modules.post.post_recommendation_module.constants import (
    CATEGORY_NAMES, CATEGORY_EXPIRY_DAYS, COMMODITY_ID_TO_IDX,
    DEFAULT_TASTE, FEED_SIZE, FETCH_TARGET, MAX_PER_AUTHOR,
    MAX_PER_CATEGORY, MIN_POOL_SIZE, POPULAR_LIMIT,
)
from app.modules.post.post_recommendation_module.models import (
    PostEmbedding, PopularPost, SeenPost, UserTasteProfile,
)
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
# Taste path: record user interaction (like / save / comment)
# ---------------------------------------------------------------------------

def record_interaction(db: Session, profile_id: int, category_id: int) -> None:
    category = CATEGORY_NAMES.get(category_id)
    if not category:
        return

    col_map = {
        "market_update": "market_update_count",
        "deal_req": "deal_req_count",
        "discussion": "discussion_count",
        "knowledge": "knowledge_count",
    }
    col = col_map.get(category)
    if not col:
        return

    taste = db.query(UserTasteProfile).filter(
        UserTasteProfile.profile_id == profile_id
    ).first()

    if taste is None:
        profile = db.query(Profile).filter(Profile.id == profile_id).first()
        if not profile:
            return
        defaults = DEFAULT_TASTE.get(profile.role_id, DEFAULT_TASTE[1])
        taste = UserTasteProfile(
            profile_id=profile_id,
            market_update_count=defaults["market_update"],
            deal_req_count=defaults["deal_req"],
            discussion_count=defaults["discussion"],
            knowledge_count=defaults["knowledge"],
            total_events=0,
        )
        db.add(taste)
        db.flush()

    setattr(taste, col, getattr(taste, col) + 1)
    taste.total_events += 1
    db.commit()


# ---------------------------------------------------------------------------
# Internal helpers for the read path
# ---------------------------------------------------------------------------

def _get_or_seed_taste(db: Session, profile_id: int, role_id: int) -> dict[str, int]:
    taste = db.query(UserTasteProfile).filter(
        UserTasteProfile.profile_id == profile_id
    ).first()
    if taste:
        return {
            "market_update": taste.market_update_count,
            "deal_req":      taste.deal_req_count,
            "discussion":    taste.discussion_count,
            "knowledge":     taste.knowledge_count,
        }
    return DEFAULT_TASTE.get(role_id, DEFAULT_TASTE[1])


def _seen_post_ids(db: Session, profile_id: int) -> set[int]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    rows = (
        db.query(SeenPost.post_id)
        .filter(SeenPost.profile_id == profile_id, SeenPost.seen_at >= cutoff)
        .order_by(SeenPost.seen_at.desc())
        .limit(100)
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

def _taste_weight(counts: dict[str, int], category: str) -> float:
    total = sum(math.log1p(v) for v in counts.values())
    if total == 0:
        return 1.0 / len(counts)
    return math.log1p(counts.get(category, 0)) / total


def _freshness(created_at: datetime) -> float:
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    age_h = (datetime.now(timezone.utc) - created_at).total_seconds() / 3600
    if age_h < 2:
        return 1.4
    if age_h < 6:
        return 1.2
    return 1.0


def _rerank(
    db: Session,
    candidates: list[dict],
    taste_counts: dict[str, int],
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
        social = 1.5 if author_user_id in followed_user_ids else 1.0

        final = (
            c["vec_score"]
            * _taste_weight(taste_counts, c["category"])
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


def _apply_diversity(scored: list[dict]) -> list[dict]:
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
        if len(result) >= FEED_SIZE:
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
            image_url=post.image_url,
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
# Main read path
# ---------------------------------------------------------------------------

def get_recommended_posts(db: Session, profile_id: int) -> list:
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        raise ValueError(f"Profile {profile_id} not found")

    commodity_ids = [pc.commodity_id for pc in profile.commodities]
    commodity_idxs = {
        COMMODITY_ID_TO_IDX[cid] for cid in commodity_ids if cid in COMMODITY_ID_TO_IDX
    }

    user_vec = build_user_feed_vector(
        commodity_ids=commodity_ids,
        role_id=profile.role_id,
        lat=float(profile.business.latitude),
        lon=float(profile.business.longitude),
        commodity_quantity=(float(profile.quantity_min) + float(profile.quantity_max)) / 2,
    )

    taste_counts = _get_or_seed_taste(db, profile_id, profile.role_id)

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

    scored = _rerank(db, pool, taste_counts, followed_user_ids)
    final = _apply_diversity(scored)

    return _build_feed_cards(db, final, profile_id)
