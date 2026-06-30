"""
Post Recommendation Service

Write path  – index_post():            called by post service on publish
Read path   – get_recommended_posts(): returns personalised feed cards
Taste path  – taste_service.get_taste_weights() (post_user_interaction)
"""
import math
from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session, selectinload
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
) -> tuple[list[dict], dict]:
    from app.modules.post.models import Post

    if not candidates:
        return [], {}

    post_ids = list({c["post_id"] for c in candidates})
    posts = {
        p.id: p
        for p in db.query(Post)
        .options(selectinload(Post.deal_details))
        .filter(Post.id.in_(post_ids))
        .all()
    }

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
    return scored, posts


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


def _build_feed_cards(
    db: Session,
    final: list[dict],
    viewer_profile_id: int,
    posts: dict | None = None,
    followed_user_ids: set | None = None,
) -> list:
    from app.modules.post.models import Post, PostLike, PostSave
    from app.modules.post.schemas import PostDealResponse, FeedPostCard
    from app.modules.post.service import _ROLE_NAMES

    if not final:
        return []

    post_ids = [f["post_id"] for f in final]
    if posts is None:
        posts = {
            p.id: p
            for p in db.query(Post)
            .options(selectinload(Post.deal_details))
            .filter(Post.id.in_(post_ids))
            .all()
        }

    author_ids = list({f["author_profile_id"] for f in final})
    authors = {
        p.id: p
        for p in db.query(Profile)
        .options(selectinload(Profile.business))
        .filter(Profile.id.in_(author_ids))
        .all()
    }

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

    cards = []
    for f in final:
        post = posts.get(f["post_id"])
        if not post:
            continue
        author = authors.get(post.profile_id)
        biz = author.business if author else None

        cards.append(FeedPostCard(
            id=post.id,
            profile_id=post.profile_id,
            category_id=post.category_id,
            commodity_id=post.commodity_id,
            title=post.title,
            caption=post.caption,
            image_urls=post.image_urls,
            source_url=post.source_url,
            location_name=post.location_name,
            location_city=biz.city if biz else None,
            location_state=biz.state if biz else None,
            allow_comments=post.allow_comments,
            deal_details=PostDealResponse.model_validate(post.deal_details) if post.deal_details else None,
            created_at=post.created_at,
            is_liked=post.id in liked_ids,
            is_saved=post.id in saved_ids,
            like_count=post.like_count,
            comment_count=post.comment_count,
            author_name=author.name if author else "",
            author_role=_ROLE_NAMES.get(author.role_id, "Trader") if author else "Trader",
            author_user_id=str(author.users_id) if author else "",
            author_company=biz.business_name if biz else None,
            author_avatar_url=author.avatar_url if author else None,
            is_following=bool(
                author and followed_user_ids and author.users_id in followed_user_ids
            ),
            is_user_verified=author.is_user_verified if author else False,
            is_business_verified=author.is_business_verified if author else False,
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
    profile = (
        db.query(Profile)
        .options(
            selectinload(Profile.commodities),
            selectinload(Profile.business),
        )
        .filter(Profile.id == profile_id)
        .first()
    )
    if not profile:
        raise ValueError(f"Profile {profile_id} not found")

    commodity_ids = [pc.commodity_id for pc in profile.commodities]
    commodity_idxs = {
        COMMODITY_ID_TO_IDX[cid] for cid in commodity_ids if cid in COMMODITY_ID_TO_IDX
    }
    # user vector fetch
    from app.modules.profile.models import UserEmbedding
    emb_row = db.query(UserEmbedding).filter(
        UserEmbedding.user_id == profile.users_id
    ).first()
    # user vector convert or build
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

    scored, posts = _rerank(db, pool, cat_weights, commodity_weights, author_weights, followed_user_ids)
    final = _apply_diversity(scored, limit=limit)

    return _build_feed_cards(db, final, profile_id, posts=posts, followed_user_ids=followed_user_ids)


def get_popular_posts(db: Session, profile_id: int, limit: int = POPULAR_LIMIT) -> list:
    """Popular posts (by velocity) for the viewer's commodities, as full feed cards.

    Standalone accessor for the home feed's blended post pipeline. Reuses the same
    PopularPost source as the recommender's internal fallback (`_get_popular_posts`),
    but returns ready-to-serve FeedPostCards instead of internal candidate dicts.
    """
    from app.modules.post.models import Post

    profile = (
        db.query(Profile)
        .options(selectinload(Profile.commodities))
        .filter(Profile.id == profile_id)
        .first()
    )
    if not profile:
        return []

    commodity_ids = [pc.commodity_id for pc in profile.commodities]
    commodity_idxs = {
        COMMODITY_ID_TO_IDX[cid] for cid in commodity_ids if cid in COMMODITY_ID_TO_IDX
    }

    popular = _get_popular_posts(db, commodity_idxs or {0, 1, 2}, exclude_ids=set())
    if not popular:
        return []

    # _build_feed_cards needs author_profile_id per entry; resolve it via Post.
    post_ids = [p["post_id"] for p in popular]
    posts = {
        p.id: p
        for p in db.query(Post)
        .options(selectinload(Post.deal_details))
        .filter(Post.id.in_(post_ids))
        .all()
    }
    final: list[dict] = []
    for p in popular:
        post = posts.get(p["post_id"])
        if not post:
            continue
        final.append({
            "post_id": p["post_id"],
            "category": p["category"],
            "author_profile_id": post.profile_id,
        })
        if len(final) >= limit:
            break

    followed_user_ids = {
        row.following_id
        for row in db.query(UserConnection.following_id)
        .filter(UserConnection.follower_id == profile.users_id)
        .all()
    }

    return _build_feed_cards(db, final, profile_id, posts=posts, followed_user_ids=followed_user_ids)



# def get_recommended_posts(db: Session, profile_id: int, limit: int = FEED_SIZE) -> list:
#     print("=== GET_RECOMMENDED_POSTS CALLED ===")
#     import time
#     _t = time.perf_counter
#     t0 = _t()

#     profile = (
#         db.query(Profile)
#         .options(selectinload(Profile.commodities), selectinload(Profile.business))
#         .filter(Profile.id == profile_id)
#         .first()
#     )
#     print(f"[FEED] profile load:       {(_t()-t0)*1000:.1f}ms"); t0=_t()
#     if not profile:
#         raise ValueError(f"Profile {profile_id} not found")

#     commodity_ids = [pc.commodity_id for pc in profile.commodities]
#     commodity_idxs = {COMMODITY_ID_TO_IDX[cid] for cid in commodity_ids if cid in COMMODITY_ID_TO_IDX}

#     from app.modules.profile.models import UserEmbedding
#     emb_row = db.query(UserEmbedding).filter(UserEmbedding.user_id == profile.users_id).first()
#     if emb_row and emb_row.post_feed_vector is not None:
#         user_vec = _parse_vec(emb_row.post_feed_vector)
#     else:
#         user_vec = build_user_feed_vector(
#             commodity_ids=commodity_ids, role_id=profile.role_id,
#             lat=float(profile.business.latitude), lon=float(profile.business.longitude),
#             commodity_quantity=(float(profile.quantity_min) + float(profile.quantity_max)) / 2,
#         )
#     print(f"[FEED] user_vec:            {(_t()-t0)*1000:.1f}ms"); t0=_t()

#     cat_weights       = taste_service.get_taste_weights(db, profile_id, "category", profile.role_id)
#     commodity_weights = taste_service.get_taste_weights(db, profile_id, "commodity")
#     author_weights    = taste_service.get_taste_weights(db, profile_id, "author")
#     print(f"[FEED] taste weights (3q):  {(_t()-t0)*1000:.1f}ms"); t0=_t()

#     followed_user_ids = {
#         row.following_id
#         for row in db.query(UserConnection.following_id)
#         .filter(UserConnection.follower_id == profile.users_id).all()
#     }
#     print(f"[FEED] followed_ids:        {(_t()-t0)*1000:.1f}ms"); t0=_t()

#     seen_ids = _seen_post_ids(db, profile_id)
#     print(f"[FEED] seen_ids ({len(seen_ids)}):      {(_t()-t0)*1000:.1f}ms"); t0=_t()

#     pool_exclude: set[int] = set(seen_ids)
#     pool: list[dict] = []

#     hot_embs = _query_partition(db, "hot", FETCH_TARGET, pool_exclude, user_vec)
#     for emb in hot_embs:
#         score = weighted_cosine_similarity(user_vec, emb["vector"])
#         pool.append({"post_id": emb["post_id"], "category": emb["category"], "vec_score": score})
#         pool_exclude.add(emb["post_id"])
#     print(f"[FEED] hot ANN ({len(hot_embs)}):       {(_t()-t0)*1000:.1f}ms"); t0=_t()

#     if len(pool) < MIN_POOL_SIZE:
#         warm_embs = _query_partition(db, "warm", FETCH_TARGET - len(pool), pool_exclude, user_vec)
#         for emb in warm_embs:
#             score = weighted_cosine_similarity(user_vec, emb["vector"])
#             pool.append({"post_id": emb["post_id"], "category": emb["category"], "vec_score": score})
#             pool_exclude.add(emb["post_id"])
#         print(f"[FEED] warm ANN ({len(warm_embs)}):      {(_t()-t0)*1000:.1f}ms"); t0=_t()

#     if len(pool) < MIN_POOL_SIZE:
#         cold_embs = _query_partition(db, "cold", FETCH_TARGET - len(pool), pool_exclude, user_vec)
#         for emb in cold_embs:
#             score = weighted_cosine_similarity(user_vec, emb["vector"])
#             pool.append({"post_id": emb["post_id"], "category": emb["category"], "vec_score": score})
#             pool_exclude.add(emb["post_id"])
#         print(f"[FEED] cold ANN ({len(cold_embs)}):      {(_t()-t0)*1000:.1f}ms"); t0=_t()

#     popular = _get_popular_posts(db, commodity_idxs or {0, 1, 2}, pool_exclude)
#     pool.extend(popular)
#     for p in popular: pool_exclude.add(p["post_id"])
#     print(f"[FEED] popular ({len(popular)}):        {(_t()-t0)*1000:.1f}ms"); t0=_t()

#     fresh = _ensure_fresh_in_pool(
#         db=db, viewer_role_id=profile.role_id,
#         commodity_idxs=commodity_idxs or {0, 1, 2},
#         exclude_ids=pool_exclude, user_vec=user_vec, limit=FRESH_SLOTS,
#     )
#     pool.extend(fresh)
#     print(f"[FEED] fresh inject ({len(fresh)}):   {(_t()-t0)*1000:.1f}ms"); t0=_t()

#     scored, posts = _rerank(db, pool, cat_weights, commodity_weights, author_weights, followed_user_ids)
#     print(f"[FEED] rerank ({len(pool)} cands):   {(_t()-t0)*1000:.1f}ms"); t0=_t()

#     final = _apply_diversity(scored, limit=limit)
#     result = _build_feed_cards(db, final, profile_id, posts=posts, followed_user_ids=followed_user_ids)
#     print(f"[FEED] build_cards ({len(final)}):   {(_t()-t0)*1000:.1f}ms")

#     return result
