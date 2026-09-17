
import logging
"""
Post Recommendation Service

Write path  – index_post():            called by post service on publish
Read path   – get_recommended_posts(): returns personalised feed cards
Taste path  – taste_service.get_taste_weights() (post_user_interaction)
"""
import math
from datetime import datetime, timezone, timedelta

import redis
from sqlalchemy import text
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.exc import IntegrityError

from app.modules.post.recommendation.constants import (
    CATEGORY_NAMES, CATEGORY_EXPIRY_DAYS, COMMODITY_ID_TO_IDX,
    FEED_SIZE, FETCH_TARGET,
    FRESH_BOOST_PEAK, FRESH_DECAY_TAU, FRESH_INJECT_HOURS, FRESH_SLOTS,
    HOT_MAX_HOURS, WARM_MAX_HOURS, PARTITION_ALLOWED,
    MAX_PER_AUTHOR, MAX_PER_CATEGORY, MIN_POOL_SIZE, POPULAR_LIMIT,
    _ROLE_NAMES,
)
from app.modules.post.data.recommendation_models import (
    PostEmbedding, PopularPost, SeenPost,
)
from app.modules.post.recommendation.session_taste import taste_service
from app.modules.post.recommendation.vectors import (
    build_post_vector,
    build_user_feed_vector,
    weighted_cosine_similarity,
)
from app.modules.profile.data.models import Profile
from app.modules.connections.data.models import UserConnection
from app.recommendation.global_session import merge_weights, sync_module_to_global
from app.recommendation.global_taste import read_global_taste_weights
from app.shared.utils.time_decay import freshness_boost

log = logging.getLogger(__name__)


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

def resolve_partition(category: str, age_hours: float) -> str | None:
    """Which partition a post of this age belongs in, or None if it belongs in none.

    Mirrors what run_expiry_job() arrives at by demoting hot -> warm -> cold: a
    category is only demoted into a partition it is allowed in, so e.g. a
    deal_req stays in "warm" until it expires rather than falling into "cold".
    Used by the backfill, which writes historical rows in one shot instead of
    waiting for the job to walk them down.
    """
    if age_hours <= HOT_MAX_HOURS:
        return "hot" if category in PARTITION_ALLOWED["hot"] else None
    if age_hours <= WARM_MAX_HOURS:
        if category in PARTITION_ALLOWED["warm"]:
            return "warm"
        return None
    if category in PARTITION_ALLOWED["cold"]:
        return "cold"
    # Past warm but not allowed in cold — it stays warm until expiry removes it.
    return "warm" if category in PARTITION_ALLOWED["warm"] else None


def index_post(
    repo,
    post_id: int,
    commodity_id: int,
    target_role_ids: list[int] | None,
    lat: float,
    lon: float,
    category_id: int,
    commodity_quantity: float | None = None,
) -> None:
    """Build and store this post's recommendation vector.

    Takes the repository, not a Session: every caller already passes `repo=`,
    and the write rides the caller's transaction so a post and its embedding
    commit together.
    """
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

    repo.upsert_post_embedding(
        post_id=post_id,
        vector=vector,
        category=category,
        commodity_idx=commodity_idx,
        expires_at=expires_at,
        now=now,
    )


# ---------------------------------------------------------------------------
# Write path: remove post from index on delete --> set is_active to False  
# ---------------------------------------------------------------------------

def remove_post_index(repo, post_id: int) -> None:
    """Drop a post out of the recommendation index. Rides the caller's transaction."""
    repo.deactivate_post_embedding(post_id)


# ---------------------------------------------------------------------------
# Taste path: record_interaction and get_taste_for_feed have moved to
# app.modules.post.post_user_interaction.service
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Internal helpers for the read path
# ---------------------------------------------------------------------------



def _seen_post_ids(repo, profile_id: int) -> set[int]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    return repo.seen_post_ids_since(profile_id, cutoff)



def record_seen(repo, profile_id: int, post_ids: list[int]) -> None:
    """Mark posts as seen so they stop being re-served."""
    if post_ids:
        repo.record_seen_posts(profile_id, post_ids)


def _query_partition(
    repo, partition: str, limit: int, exclude_ids: set[int], user_vec: list[float]
) -> list[dict]:
    """HNSW ANN pre-filter for one freshness partition.

    Returns raw vectors so the caller can apply the exact weighted cosine for
    the final vec_score. The SQL lives in the repository; this only shapes the
    request.
    """
    vec_str = "[" + ",".join(str(v) for v in user_vec) + "]"
    return repo.ann_post_candidates(vec_str, partition, limit, exclude_ids)


def _get_popular_posts(
    repo, commodity_idxs: set[int], exclude_ids: set[int]
) -> list[dict]:
    """Platform-popular posts for the viewer's commodities, as pool entries."""
    rows = repo.popular_post_candidates(commodity_idxs, exclude_ids, POPULAR_LIMIT)
    return [
        {"post_id": r.post_id, "category": r.category, "vec_score": 0.5}
        for r in rows
    ]


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


def _location_multiplier(
    city_weights: dict[str, float],
    state_weights: dict[str, float],
    post_city: str | None,
    post_state: str | None,
) -> float:
    """City takes priority over state — state is only consulted when city has no signal."""
    if post_city and city_weights:
        score = city_weights.get(post_city.strip().lower(), 0.0)
        if score > 0:
            max_score = max(city_weights.values())
            return 1.0 + 0.3 * min(score / max(max_score, 0.05), 1.0)
    if post_state and state_weights:
        score = state_weights.get(post_state.strip().lower(), 0.0)
        if score > 0:
            max_score = max(state_weights.values())
            return 1.0 + 0.3 * min(score / max(max_score, 0.05), 1.0)
    return 1.0


def _freshness(created_at: datetime) -> float:
    return freshness_boost(created_at, FRESH_BOOST_PEAK, FRESH_DECAY_TAU)


def _rerank(
    repo,
    candidates: list[dict],
    cat_weights: dict[str, float],
    commodity_weights: dict[str, float],
    author_weights: dict[str, float],
    city_weights: dict[str, float],
    state_weights: dict[str, float],
    followed_user_ids: set,
) -> tuple[list[dict], dict]:
    from app.modules.post.data.models import Post

    if not candidates:
        return [], {}

    post_ids = list({c["post_id"] for c in candidates})
    posts = {p.id: p for p in repo.get_posts_by_ids(post_ids)}

    profile_ids = list({p.profile_id for p in posts.values()})
    profiles = repo.get_authors_with_business(profile_ids)

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

        author_biz = author_profile.business if author_profile else None
        post_city = author_biz.city if author_biz else None
        post_state = author_biz.state if author_biz else None

        final = (
            c["vec_score"]
            * _category_weight(cat_weights, c["category"])
            * _commodity_multiplier(commodity_weights, post.commodity_id)
            * _location_multiplier(city_weights, state_weights, post_city, post_state)
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
    # `profiles` goes back with the rest so _build_feed_cards does not fetch the
    # same authors again. Locally that is a couple of milliseconds; against a
    # database a round trip away it is two round trips per feed request.
    return scored, posts, profiles


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
    repo,
    final: list[dict],
    viewer_profile_id: int,
    posts: dict | None = None,
    followed_user_ids: set | None = None,
    authors: dict | None = None,
) -> list:
    from app.modules.post.data.models import Post, PostLike, PostSave
    from app.modules.post.application.schemas import PostDealResponse, FeedPostCard

    if not final:
        return []

    post_ids = [f["post_id"] for f in final]
    if posts is None:
        posts = {p.id: p for p in repo.get_posts_by_ids(post_ids)}

    if authors is None:
        author_ids = list({p.profile_id for p in posts.values()})
        authors = repo.get_authors_with_business(author_ids)

    liked_ids = repo.liked_post_ids(viewer_profile_id, post_ids)
    saved_ids = repo.saved_post_ids(viewer_profile_id, post_ids)

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
    repo,
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

    rows = repo.fresh_post_candidates(cutoff, limit * 3, commodity_idxs, exclude_ids)

    result = []
    for r in rows:
        target = r["target_roles"]
        if target and viewer_role_id not in target:
            continue
        vec_score = weighted_cosine_similarity(user_vec, r["vector"])
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

def get_recommended_posts(
    repo,
    profile_id: int,
    limit: int = FEED_SIZE,
    rc: redis.Redis | None = None,
) -> list:
    profile = repo.get_profile_with_commodities(profile_id)
    if not profile:
        raise ValueError(f"Profile {profile_id} not found")

    commodity_ids = [pc.commodity_id for pc in profile.commodities]
    commodity_idxs = {
        COMMODITY_ID_TO_IDX[cid] for cid in commodity_ids if cid in COMMODITY_ID_TO_IDX
    }
    # user vector fetch
    stored_vec = repo.user_post_feed_vector(profile.users_id)
    # user vector convert or build
    if stored_vec is not None:
        user_vec = _parse_vec(stored_vec)
    else:
        user_vec = build_user_feed_vector(
            commodity_ids=commodity_ids,
            role_id=profile.role_id,
            lat=float(profile.business.latitude),
            lon=float(profile.business.longitude),
            commodity_quantity=(float(profile.quantity_min) + float(profile.quantity_max)) / 2,
        )

    # One query for all three dimensions; they live in the same table.
    _taste = taste_service.get_taste_weights_bulk(
        repo.session, profile_id, ("category", "commodity", "author"), profile.role_id
    )
    cat_weights       = _taste["category"]
    commodity_weights = _taste["commodity"]
    author_weights    = _taste["author"]
    city_weights      = read_global_taste_weights(repo.session, profile_id, "city")
    state_weights     = read_global_taste_weights(repo.session, profile_id, "state")

    try:
        sync_module_to_global(rc, profile_id, "post")
        cat_weights       = merge_weights(rc, profile_id, "post", "category",  cat_weights)
        commodity_weights = merge_weights(rc, profile_id, "post", "commodity", commodity_weights)
        author_weights    = merge_weights(rc, profile_id, "post", "author",    author_weights)
        city_weights      = merge_weights(rc, profile_id, "post", "city",      city_weights)
        state_weights     = merge_weights(rc, profile_id, "post", "state",     state_weights)
    except Exception as exc:
        # Fall back to the persistent weights already loaded above.
        log.warning("session-taste merge failed for profile %s; ranking on persistent taste only: %s", profile_id, exc)

    followed_user_ids = repo.all_followed_user_ids(profile.users_id)

    seen_ids = _seen_post_ids(repo, profile_id)
    pool_exclude: set[int] = set(seen_ids)
    pool: list[dict] = []

    hot_embs = _query_partition(repo, "hot", FETCH_TARGET, pool_exclude, user_vec)
    for emb in hot_embs:
        score = weighted_cosine_similarity(user_vec, emb["vector"])
        pool.append({"post_id": emb["post_id"], "category": emb["category"], "vec_score": score})
        pool_exclude.add(emb["post_id"])

    if len(pool) < MIN_POOL_SIZE:
        warm_embs = _query_partition(repo, "warm", FETCH_TARGET - len(pool), pool_exclude, user_vec)
        for emb in warm_embs:
            score = weighted_cosine_similarity(user_vec, emb["vector"])
            pool.append({"post_id": emb["post_id"], "category": emb["category"], "vec_score": score})
            pool_exclude.add(emb["post_id"])

    if len(pool) < MIN_POOL_SIZE:
        cold_embs = _query_partition(repo, "cold", FETCH_TARGET - len(pool), pool_exclude, user_vec)
        for emb in cold_embs:
            score = weighted_cosine_similarity(user_vec, emb["vector"])
            pool.append({"post_id": emb["post_id"], "category": emb["category"], "vec_score": score})
            pool_exclude.add(emb["post_id"])

    popular = _get_popular_posts(repo, commodity_idxs or {0, 1, 2}, pool_exclude)
    pool.extend(popular)
    for p in popular:
        pool_exclude.add(p["post_id"])

    # Guarantee fresh posts are in the pool even if the hot ANN missed them.
    # They enter with their actual vec_score and compete via score + freshness boost.
    fresh = _ensure_fresh_in_pool(
        repo=repo,
        viewer_role_id=profile.role_id,
        commodity_idxs=commodity_idxs or {0, 1, 2},
        exclude_ids=pool_exclude,
        user_vec=user_vec,
        limit=FRESH_SLOTS,
    )
    pool.extend(fresh)

    scored, posts, authors = _rerank(
        repo, pool, cat_weights, commodity_weights, author_weights,
        city_weights, state_weights, followed_user_ids,
    )
    final = _apply_diversity(scored, limit=limit)

    return _build_feed_cards(repo, final, profile_id, posts=posts,
                             followed_user_ids=followed_user_ids, authors=authors)
