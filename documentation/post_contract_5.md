# Post Module API Contract — v5

> Reflects codebase state as of 2026-06-04.
>
> **Changes from v4:**
> - `time_elapsed` computed field added to `PostResponse` and `FeedPostCard` — server-side human-readable age string ("3 hours ago", "2 days ago").
> - `GET /posts/recommendation/feed` now accepts a `limit` query param (1–50, default 25).
> - Feed response changed from `FeedPostCard[]` to `FeedResponse { posts, has_more }` — client knows when the pool is exhausted.
> - Infinite-feed mechanism: seen-post exclusion is now the sole scroll cursor. No delivered-post suppression. No offset pagination.
> - Freshness boost changed from step function (1.4/1.2/1.0 tiers) to continuous exponential decay.
> - Fresh post guarantee: posts < 4h old are always injected into the candidate pool and ranked by score.
> - Seen-post exclusion window is 30 days with no entry cap (previously capped at 100).
> - `MAX_PER_CATEGORY` raised from 3 → 8 and `MAX_PER_AUTHOR` from 2 → 3 to allow fuller feeds.

---

## Base URL

```
/posts
```

All endpoints require a valid JWT (`Authorization: Bearer <token>`). `profile_id` is resolved server-side from the token.

---

## Post Categories

| id | name               |
|----|--------------------|
| 1  | Market Update      |
| 2  | Knowledge          |
| 3  | Discussion         |
| 4  | Deal / Requirement |

---

## Schemas

### PostDealCreate
Required when `category_id == 4`.

```json
{
  "grain_type":         "string",
  "grain_size":         "string",
  "commodity_quantity": "float",
  "quantity_unit":      "string",   // "MT" | "quintal"
  "commodity_price":    "float",
  "price_type":         "string"    // "fixed" | "negotiable"
}
```

### PostDealUpdate
All fields optional. `is_closed` is not editable here — use `POST /{id}/close`.

```json
{
  "grain_type":         "string?",
  "grain_size":         "string?",
  "commodity_quantity": "float?",
  "quantity_unit":      "string?",
  "commodity_price":    "float?",
  "price_type":         "string?"
}
```

### PostDealResponse

```json
{
  "grain_type":         "string",
  "grain_size":         "string",
  "commodity_quantity": "float",
  "quantity_unit":      "string",
  "commodity_price":    "float",
  "price_type":         "string",
  "is_closed":          "bool"
}
```

### PostCreate

```json
{
  "category_id":    "int",             // 1–4, required
  "commodity_id":   "int",             // 1=Rice  2=Cotton  3=Sugar
  "title":          "string",          // required, non-empty
  "caption":        "string",          // required, non-empty
  "is_public":      "bool",            // default: true
  "target_roles":   "[int]?",          // null=all roles  [1/2/3]=specific
  "allow_comments": "bool",            // default: true
  "image_url":      "string?",         // from /upload-image step
  "source_url":     "string?",         // external info source link
  "location_name":  "string?",         // human-readable place label
  "latitude":       "float?",          // overrides author location in recommendation
  "longitude":      "float?",
  "deal_details":   "PostDealCreate?"  // required if category_id == 4
}
```

### PostUpdate (PATCH — all fields optional)

```json
{
  "title":          "string?",
  "caption":        "string?",
  "image_url":      "string?",
  "source_url":     "string?",
  "location_name":  "string?",
  "latitude":       "float?",
  "longitude":      "float?",
  "is_public":      "bool?",
  "target_roles":   "[int]?",
  "allow_comments": "bool?",
  "deal_details":   "PostDealUpdate?"
}
```

### PostResponse

```json
{
  "id":            "int",
  "profile_id":    "int",
  "category_id":   "int",
  "commodity_id":  "int",
  "title":         "string",
  "caption":       "string",
  "image_url":     "string?",
  "source_url":    "string?",
  "location_name": "string?",
  "latitude":      "float?",
  "longitude":     "float?",
  "is_public":     "bool",
  "target_roles":  "[int]?",
  "allow_comments":"bool",
  "deal_details":  "PostDealResponse?",
  "view_count":    "int",
  "like_count":    "int",
  "comment_count": "int",
  "share_count":   "int",
  "save_count":    "int",
  "is_liked":      "bool",
  "is_saved":      "bool",
  "created_at":    "datetime",
  "time_elapsed":  "string"            // computed: "3 hours ago", "2 days ago", etc.
}
```

### FeedPostCard
Returned inside `FeedResponse.posts`. Flat structure — post and author data merged.

```json
{
  "id":            "int",
  "profile_id":    "int",
  "category_id":   "int",
  "commodity_id":  "int",
  "title":         "string",
  "caption":       "string",
  "image_url":     "string?",
  "source_url":    "string?",
  "location_name": "string?",          // pre-built: post location OR "city, state"
  "latitude":      "float?",
  "longitude":     "float?",
  "is_public":     "bool",
  "target_roles":  "[int]?",
  "allow_comments":"bool",
  "deal_details":  "PostDealResponse?",
  "view_count":    "int",
  "like_count":    "int",
  "comment_count": "int",
  "share_count":   "int",
  "save_count":    "int",
  "is_liked":      "bool",
  "is_saved":      "bool",
  "created_at":    "datetime",
  "time_elapsed":  "string",           // computed: "just now", "2 hours ago", etc.

  "author_name":          "string",
  "author_role":          "string",    // "trader" | "broker" | "exporter"
  "author_user_id":       "string",    // UUID — required for Follow button
  "author_company":       "string?",
  "author_avatar_url":    "string?",
  "is_user_verified":     "bool",
  "is_business_verified": "bool",

  "comment_preview_author": "string?", // latest commenter name, null if no comments
  "comment_preview_text":   "string?"  // latest comment text (first 60 chars)
}
```

### FeedResponse
Returned by `GET /posts/recommendation/feed`.

```json
{
  "posts":    "FeedPostCard[]",
  "has_more": "bool"
}
```

`has_more: true` — batch is full; more unseen posts exist. Call the feed endpoint again after marking current batch seen.
`has_more: false` — pool is exhausted; no more unseen posts available.

### PostSeenPayload

```json
{ "post_ids": "[int]" }
```

---

## `time_elapsed` Field

Computed server-side from `created_at`. Returned on both `PostResponse` and `FeedPostCard`.

| Age | Value |
|---|---|
| < 60 seconds | `"just now"` |
| 1–59 minutes | `"N minute(s) ago"` |
| 1–23 hours | `"N hour(s) ago"` |
| 1–6 days | `"N day(s) ago"` |
| 1–4 weeks | `"N week(s) ago"` |
| 1+ months | `"N month(s) ago"` |

---

## Endpoints

### Image Upload

#### `POST /posts/upload-image`

**Query params:** `content_type` — `image/jpeg` | `image/png` | `image/webp`

**Response `200`:**
```json
{ "upload_url": "string", "image_url": "string", "content_type": "string" }
```

**Errors:** `400` unsupported content_type

---

### Posts CRUD

#### `POST /posts/`
Create a post. **Response `201`:** `PostResponse`

#### ~~`GET /posts/`~~ *(disabled — no active use case)*

#### `GET /posts/mine`
Posts by the authenticated profile, newest first. **Query:** `limit`, `offset`. **Response `200`:** `PostResponse[]`

#### `GET /posts/following`
Posts from followed users (last 7 days), newest first. **Query:** `limit`, `offset`. **Response `200`:** `PostResponse[]`

#### `GET /posts/saved`
Saved posts, newest save first. **Query:** `limit`, `offset`. **Response `200`:** `PostResponse[]`

#### `GET /posts/{post_id}`
Fetch a single post. Records a view (once per profile). Marks the post as seen in the recommendation engine.
**Response `200`:** `PostResponse` | **Errors:** `404`

#### `PATCH /posts/{post_id}`
Update own post. `is_closed` not editable here.
**Response `200`:** `PostResponse` | **Errors:** `403`, `404`

#### `DELETE /posts/{post_id}`
Delete own post. Cascades to all interactions. Removes S3 image if present.
**Response `204`** | **Errors:** `403`, `404`

---

### Interactions

#### `POST /posts/{post_id}/like`
Toggle like. **Response `200`:** `{ "liked": bool, "like_count": int }` | **Errors:** `404`

#### `GET /posts/{post_id}/comments`
Oldest first. **Query:** `limit`, `offset`. **Response `200`:** `CommentResponse[]` | **Errors:** `404`

#### `POST /posts/{post_id}/comments`
**Body:** `{ "content": string }`. **Response `201`:** `CommentResponse` | **Errors:** `403` (disabled), `404`, `422`

#### `DELETE /posts/{post_id}/comments/{comment_id}`
Author only. **Response `204`** | **Errors:** `403`, `404`

#### `POST /posts/{post_id}/share`
Not idempotent — each call increments `share_count`.
**Response `200`:** `{ "share_count": int }` | **Errors:** `404`

#### `POST /posts/{post_id}/save`
Toggle save. **Response `200`:** `{ "saved": bool }` | **Errors:** `404`

#### `POST /posts/{post_id}/close`
Toggle `is_closed` on a Deal post. Owner only. Closing removes from recommendation pool; reopening re-indexes.
**Response `200`:** `{ "is_closed": bool }` | **Errors:** `403`, `404`

---

## Recommendation Feed

### `GET /posts/recommendation/feed`

Returns a personalised feed. Each call is stateless — the pipeline re-evaluates from scratch using the current seen-post set as the exclusion cursor.

**Query params:**

| param | type | default | range | description |
|---|---|---|---|---|
| `limit` | int | 25 | 1–50 | number of posts to return |

**Response `200`:** `FeedResponse`

```json
{
  "posts": [ ...FeedPostCard ],
  "has_more": true
}
```

**Scoring pipeline:**

```
1. Exclude posts seen in last 30 days (no entry cap)
2. ANN retrieval: hot → warm → cold (sequential, stops when pool ≥ 80)
3. Popular posts fallback (top 30 by velocity, user's commodity)
4. Fresh pool guarantee: posts < 4h old injected with actual similarity scores
5. Rerank: vec_score × taste_weight × (1 + engagement) × freshness × social_boost
6. Diversity: max 8 per category, max 3 per author
7. Return top `limit` posts
```

**Freshness boost (continuous exponential decay):**
```
freshness = 1.0 + 0.4 × e^(−age_hours / 8)

age=0h  → 1.40×   age=6h  → 1.19×
age=2h  → 1.31×   age=12h → 1.09×
age=4h  → 1.24×   age=48h → ≈1.00×
```

**`has_more` semantics:**
- `true` — batch is full (`len(posts) == limit`); unseen posts likely remain
- `false` — batch is smaller than `limit`; pool is exhausted

**Errors:** `404` profile not found

---

## Infinite Feed Flow

```
1. GET /feed?limit=25        → 25 posts, has_more: true
   (user scrolls)

2. POST /seen {post_ids:[1..10]}  → 204
   (user continues scrolling)

3. POST /seen {post_ids:[11..20]} → 204
   (user reaches end of batch)

4. GET /feed?limit=25        → next 25 (excludes seen 1..20), has_more: true
   (new post published between steps 1 and 4 is eligible here)

5. Repeat until has_more: false
```

**Key rules:**
- Only posts explicitly sent via `POST /seen` are excluded from future feeds
- Refreshing without sending seen returns the same posts — correct behaviour
- A post seen 31+ days ago resurfaces as eligible
- New posts are eligible immediately on the next feed call

---

### Seen Posts

#### `POST /posts/recommendation/seen`

Mark posts as seen. Frontend decides the threshold (dwell time, scroll-past, explicit open).
Excluded from recommendation feed for 30 days.

Opening a post via `GET /posts/{post_id}` also marks it seen unconditionally.

**Body:** `{ "post_ids": [42, 17, 93] }` **Response `204`** | **Errors:** `422` post_ids empty

---

### Background Jobs (internal / admin)

#### `POST /posts/recommendation/jobs/expiry`
Ages hot→warm→cold, soft-expires past-expiry posts, hard-deletes cold posts > 30 days.

#### `POST /posts/recommendation/jobs/popular-sync`
Recomputes velocity scores. Replaces `popular_posts` table (delete-all + bulk insert).

Both return: `{ "status": "ok", "details": { ... } }`

---

## Location Behaviour

| Scenario | Geo used in recommendation |
|---|---|
| Post has `latitude` + `longitude` | Post coordinates |
| Post has only `location_name` | Author's business coordinates |
| No location set | Author's business coordinates |

`location_name` in `FeedPostCard` is pre-built by the server: `post.location_name` if set, else `"city, state"` from author's business profile.

---

## Seen Post Behaviour

| Event | Seen recorded |
|---|---|
| `POST /posts/recommendation/seen` | Yes — immediately |
| `GET /posts/{post_id}` (open post) | Yes — unconditionally |
| Post appears in feed, no signal sent | No — reappears on next feed call |
| Seen entry older than 30 days | Expired — post becomes eligible again |

---

## Business Rules

1. `deal_details` required when `category_id == 4`, ignored for all other categories.
2. `is_closed` only via `POST /{id}/close`, not PATCH.
3. View counted once per profile (unique constraint on `post_views`).
4. `like` and `save` update the persistent taste profile used in feed scoring.
5. `target_roles: null` = all roles. `[1,2,3]` = restricted visibility.
6. Image must be uploaded via `/upload-image` before referencing in `PostCreate`.
7. `latitude` + `longitude` must both be provided together — one alone has no effect on recommendation scoring.
8. Feed is stateless — no server-side session or delivery state between calls.
9. `has_more: false` means the pool is exhausted for the current seen set. New posts published after this point become eligible on the next call.
