# Post Recommendation Module — API Documentation

**Base URL:** `https://vanijyaa-backend.onrender.com`  
**All responses follow the envelope format:**

```json
{
  "success": true,
  "message": "...",
  "data": { ... }
}
```

> **Auth note:** All endpoints require `Authorization: Bearer <access_token>`. The `profile_id` is read from the JWT's `pid` claim automatically — no query parameter needed.

---

## How It Works — Overview

The recommendation engine runs in four layers:

```
Publish time  →  post vector (11-dim) built + stored in post_embeddings (VECTOR(11))
Feed request  →  user vector built
                 → HNSW ANN fetch: top N posts per partition ordered by cosine distance
                 → exact weighted cosine (FEED_WEIGHTS) applied in Python
                 → rerank by taste + freshness + engagement + social
                 → diversity cap → top 25 returned
```

### Storage

`post_embeddings.vector` is a native **pgvector `VECTOR(11)`** column with an HNSW index:

```sql
CREATE INDEX ix_post_embeddings_hnsw
  ON post_embeddings USING hnsw (vector vector_cosine_ops);
```

This replaces the previous JSONB storage (migrated by `a3b4c5d6e7f8`).

### Partitions

Posts age through three partitions automatically (background job, hourly):

| Partition | Age window | Categories allowed |
|-----------|------------|--------------------|
| `hot` | 0 – 72 h | All (market_update, deal_req, knowledge, discussion, other) |
| `warm` | 72 – 120 h | deal_req, knowledge, discussion, other |
| `cold` | 120 – 720 h | knowledge only |

Posts outside these windows are soft-expired (`is_active = false`) and never served.

**Candidate fetch per partition (HNSW, not random):**

The engine queries each partition using pgvector's `<=>` operator, so the candidates it fetches are already the most semantically relevant posts for this user — not an arbitrary sample:

```sql
SELECT post_id, category, vector
FROM post_embeddings
WHERE partition = 'hot' AND is_active = true
ORDER BY vector <=> '[user_vec]'::vector   -- HNSW index used here
LIMIT 50
```

Python then applies exact **weighted cosine similarity** (`FEED_WEIGHTS`: commodity 3×, role 2×, geo 1.5×, qty 1×) on the returned vectors for the final `vec_score`.

### Scoring Formula

```
final_score = vec_score × taste_weight × (1 + engagement) × freshness × social_boost
```

| Factor | What it is |
|--------|-----------|
| `vec_score` | Weighted cosine similarity between user and post vectors (commodity 3×, role 2×, geo 1.5×, qty 1×), computed in Python after HNSW pre-filtering |
| `taste_weight` | log1p-scaled share of user's historical interactions for this category |
| `engagement` | `log1p(saves×3 + comments×2 + likes) / 6.9`, capped at 1.0 |
| `freshness` | `1.4` if < 2 h old, `1.2` if < 6 h, `1.0` otherwise |
| `social_boost` | `1.5` if the post author is followed by the viewer, `1.0` otherwise |

### Diversity Caps (applied last)

| Cap | Value |
|-----|-------|
| Max posts per category | 3 |
| Max posts per author | 2 |
| Total feed size | 25 |

---

## Table of Contents

1. [Get Recommended Feed](#1-get-recommended-feed)
2. [Trigger Expiry Job](#2-trigger-expiry-job)
3. [Trigger Popular-Posts Sync](#3-trigger-popular-posts-sync)
4. [Error Reference](#4-error-reference)
5. [Testing Checklist](#5-testing-checklist)

---

## Response Object — Recommended Post

Each item in the feed response contains only the **post ID and its score**. The frontend should use these IDs to hydrate full post cards via [`GET /posts/{post_id}`](posts_api.md#5-get-single-post).

```json
{
  "post_id": 42,
  "score": 0.847231
}
```

| Field | Type | Description |
|-------|------|-------------|
| `post_id` | int | ID of the recommended post |
| `score` | float | Composite recommendation score (higher = more relevant) |

---

## 1. Get Recommended Feed

**`GET /posts/recommendation/feed`**

Returns up to 25 personalised post recommendations for the authenticated user. The response contains only `post_id` + `score` — no post content is hydrated here.

> **Seen deduplication:** Post IDs returned are recorded in `seen_posts`. The same post will not be served again for 30 days.

**Auth:** `Authorization: Bearer <access_token>` — `profile_id` is resolved from the token automatically.

### Response — `200 OK`

```json
{
  "success": true,
  "message": "...",
  "data": [
    { "post_id": 42, "score": 0.847231 },
    { "post_id": 17, "score": 0.763904 },
    { "post_id": 88, "score": 0.701455 },
    { "post_id": 5,  "score": 0.688122 }
  ]
}
```

> `data` is an array (may be empty `[]` if no eligible posts exist).

### How to Use This Response (Frontend Flow)

```
1. Call GET /posts/recommendation/feed  →  get list of {post_id, score}
2. For each post_id, call GET /posts/{post_id}?profile_id={profile_id}
   to fetch the full post card (caption, image, counts, is_liked, etc.)
3. Render cards in the order returned by step 1 (already ranked best-first)
```

> **Tip:** You can batch-fetch post details in parallel. The order from step 1 is the render order.

### Errors

| Status | Reason |
|--------|--------|
| `401` | Missing or invalid Bearer token |
| `404` | No profile found for the authenticated user |

---

## 2. Trigger Expiry Job

**`POST /posts/recommendation/jobs/expiry`**

Manually runs the hourly expiry + partition-migration job. Normally run automatically by the scheduler — this endpoint is for testing or manual ops.

**What it does:**
1. Soft-expires posts whose `expires_at` has passed (sets `is_active = false`)
2. Migrates `hot → warm` for posts older than 72 h (if category is allowed in warm)
3. Migrates `warm → cold` for posts older than 120 h (knowledge only)
4. Hard-deletes cold posts older than 30 days

### Request

No body required.

### Response — `200 OK`

```json
{
  "status": "ok",
  "details": {
    "soft_expired": 3,
    "migrated_to_warm": 8,
    "migrated_to_cold": 1,
    "hard_deleted": 0
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `soft_expired` | int | Posts marked inactive (past `expires_at`) |
| `migrated_to_warm` | int | Posts moved from hot → warm partition |
| `migrated_to_cold` | int | Posts moved from warm → cold partition |
| `hard_deleted` | int | Embedding rows permanently deleted (cold > 30 days) |

---

## 3. Trigger Popular-Posts Sync

**`POST /posts/recommendation/jobs/popular-sync`**

Manually runs the 15-minute popular-posts velocity sync. Normally run automatically by the scheduler.

**What it does:**
- Scores all active posts in the last 30 days using:  
  `velocity = (saves×3 + comments×2 + likes) / (hours_since_post + 1)^1.5`
- Keeps the top 50 per commodity in `popular_posts`
- Removes posts no longer in the top 50

Popular posts are injected into every user's recommendation pool as a baseline (useful for new users with no interaction history).

### Request

No body required.

### Response — `200 OK`

```json
{
  "status": "ok",
  "details": {
    "synced": 47,
    "top_ids_count": 47
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `synced` | int | Number of popular_posts rows upserted |
| `top_ids_count` | int | Total unique post IDs in the top-50 pool |

---

## 4. Error Reference

All errors follow this shape:

```json
{
  "detail": "Profile not found – complete onboarding first"
}
```

| HTTP Status | Meaning | When it happens |
|-------------|---------|-----------------|
| `200` | OK | Feed or job result returned |
| `404` | Not Found | No profile found for the given `profile_id` |
| `422` | Unprocessable Entity | `profile_id` missing or not an integer |
| `500` | Server Error | Unexpected failure — check server logs |

---

## 5. Testing Checklist

Use this to verify the recommendation module end-to-end.

### Prerequisites

- [ ] Server running: `uvicorn main:app --reload`  
- [ ] DB migrated: `alembic upgrade head`  
- [ ] At least 2 profiles exist with different commodities/roles  
- [ ] At least 5–10 posts created across different categories  
- [ ] Valid JWT for at least one user

### Feed

- [ ] `GET /posts/recommendation/feed` with valid `Authorization: Bearer <token>` → `200`, array of `{post_id, score}`
- [ ] Scores are floats between 0 and ~3 (composite, not clamped to 1)
- [ ] Array has at most 25 items
- [ ] Call feed again with the same token → same posts **not** returned (seen deduplication)
- [ ] `GET /posts/recommendation/feed` without Authorization header → `401`
- [ ] `GET /posts/recommendation/feed` for a user with no profile → `404`
- [ ] Fetch a returned `post_id` via `GET /posts/{post_id}` with the same Bearer token → full post card loads correctly

### Scoring behaviour

- [ ] Profile A trades Cotton → feed contains mostly Cotton posts (commodity match)
- [ ] Profile A follows Profile B → Profile B's posts get `social_boost` (score ~1.5× higher than equivalent unfollowed post)
- [ ] Like / save a Deal/Requirement post → subsequent feeds weight deal_req higher for that profile
- [ ] A very new post (< 2 h old) scores higher than an older equivalent post (`freshness` boost)

### Jobs

- [ ] `POST /posts/recommendation/jobs/expiry` → `200`, response has `soft_expired`, `migrated_to_warm`, `migrated_to_cold`, `hard_deleted` keys
- [ ] `POST /posts/recommendation/jobs/popular-sync` → `200`, response has `synced` and `top_ids_count` keys
- [ ] After popular-sync, new users with no history still get a non-empty feed (popular posts as baseline)

### Script Testing

```bash
# Test recommendation for all profiles (dry_run — seen_posts not updated)
python scripts/test_recommendation.py

# Test for specific profiles only
python scripts/test_recommendation.py --profile 1 3

# Clear seen_posts first, then test (useful after seeding many posts)
python scripts/test_recommendation.py --reset-seen

# Reset seen_posts + test specific profile
python scripts/test_recommendation.py --profile 2 --reset-seen
```

**Expected script output:**

```
Running recommendation test for 2 profile(s)…

============================================================
  Profile ID : 1
  Name       : Ravi Kumar
  Role       : Trader
  Commodities: Rice, Cotton
  Location   : (18.5204, 73.8567)
  Qty range  : 100 – 2000 MT
------------------------------------------------------------
  #    post_id    score      category           caption
  ---- ---------- ---------- ------------------ ------------------------------
  1    42         0.8472     Deal/Req           Looking for 500 MT basmati…
  2    17         0.7639     Market Update      Cotton prices up this week…
  3    88         0.7014     Discussion         Anyone trading sugar futures…

  Total returned: 3
```

---

## Quick Reference — All Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/posts/recommendation/feed` | Bearer access token | Get personalised feed (up to 25 posts) |
| `POST` | `/posts/recommendation/jobs/expiry` | None | Run expiry + partition migration job |
| `POST` | `/posts/recommendation/jobs/popular-sync` | None | Run popular-posts velocity sync |

---

## Integration Notes for Frontend

### Recommended Feed Flow

```
Home screen loads
  └─► GET /posts/recommendation/feed   (Authorization: Bearer <token>)
        └─► for each post_id in response (in order):
              GET /posts/{post_id}      (same Bearer token)
              → render post card
```

### Pagination

The recommendation feed does **not** use `limit`/`offset`. It returns up to 25 posts per call, and the seen-post filter automatically ensures the next call returns a fresh batch. Simply call the feed endpoint again when the user reaches the end of the list.

### Empty Feed

If `data` is `[]`:
- The user may have seen all available posts in the last 30 days
- There may be no posts indexed yet (run `POST /posts/recommendation/jobs/popular-sync` to prime the pool)
- Fall back to `GET /posts/` with the same Bearer token (chronological feed) as a graceful degradation

### Post Object Fields Changed from Old Posts API

The posts module was updated alongside the recommendation engine. Two fields changed:

| Old field | New fields | Used when |
|-----------|------------|-----------|
| `commodity_quantity` | `commodity_quantity_min` + `commodity_quantity_max` | Category 4 (Deal/Requirement) only |

Both new fields are `float \| null`. Update any forms or display components that previously referenced `commodity_quantity`.
