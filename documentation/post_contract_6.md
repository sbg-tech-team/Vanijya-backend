# Post Module API Contract — v6

> Reflects codebase state as of 2026-06-08.
>
> **Changes from v5:**
> - `image_url` (single string) replaced by `image_urls` (list of strings) on `PostCreate`, `PostUpdate`, `PostResponse`, and `FeedPostCard` — supports multiple images per post.
> - New endpoint `POST /posts/interactions/batch` — high-volume behavioural signal ingestion (impression, dwell, open events, link clicks).
> - `POST /posts/recommendation/seen` is **deprecated and a no-op**. Seen-post recording is now automatic: a `dwell` event with `value_ms >= 3000` marks the post seen server-side. `GET /posts/{id}` still marks seen unconditionally.
> - Feed scoring formula upgraded from 4 factors to 6: added commodity affinity multiplier and author affinity multiplier.
> - `like`, `save`, `comment`, `share` now update the persistent taste profile (category + commodity + author dimensions) in addition to incrementing counts.
> - Negative signals are now inferred automatically: bounce dwells (`value_ms < 2000`) and repeated impressions with no engagement apply downranking pressure without any frontend action.
> - Author affinity: authors whose posts a user engages with receive a `1.0–1.2×` ranking boost for non-followed authors (followed authors retain the existing `1.5×` social boost).
> - Seen-post exclusion extended — dwell-based seen is now the primary mechanism; explicit `POST /seen` removed from the infinite-feed flow.

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
  "category_id":    "int",              // 1–4, required
  "commodity_id":   "int",              // 1=Rice  2=Cotton  3=Sugar
  "title":          "string",           // required, non-empty
  "caption":        "string",           // required, non-empty
  "is_public":      "bool",             // default: true
  "target_roles":   "[int]?",           // null=all roles  [1/2/3]=specific
  "allow_comments": "bool",             // default: true
  "image_urls":     "[string]?",        // list of URLs from /upload-image — max N images
  "source_url":     "string?",          // external info source link
  "location_name":  "string?",          // human-readable place label
  "latitude":       "float?",           // overrides author location in recommendation
  "longitude":      "float?",
  "deal_details":   "PostDealCreate?"   // required if category_id == 4
}
```

### PostUpdate (PATCH — all fields optional)

```json
{
  "title":          "string?",
  "caption":        "string?",
  "image_urls":     "[string]?",
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
  "image_urls":    "[string]?",          // list of image URLs; null if no images
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
  "time_elapsed":  "string"              // computed: "3 hours ago", "2 days ago", etc.
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
  "image_urls":    "[string]?",          // list of image URLs; null if no images
  "source_url":    "string?",
  "location_name": "string?",            // pre-built: post location OR "city, state"
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
  "time_elapsed":  "string",             // computed: "just now", "2 hours ago", etc.

  "author_name":          "string",
  "author_role":          "string",      // "trader" | "broker" | "exporter"
  "author_user_id":       "string",      // UUID — required for Follow button
  "author_company":       "string?",
  "author_avatar_url":    "string?",
  "is_user_verified":     "bool",
  "is_business_verified": "bool",

  "comment_preview_author": "string?",   // latest commenter name; null if no comments
  "comment_preview_text":   "string?"    // latest comment text; null if no comments
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

`has_more: true` — batch is full; more unseen posts likely remain.
`has_more: false` — pool is exhausted for the current seen-post set.

### InteractionEventItem

```json
{
  "post_id":     "int",
  "event_type":  "string",     // see Event Types table below
  "value_ms":    "int?",       // required for dwell; omit for all other types
  "occurred_at": "datetime"    // ISO 8601 UTC — the time the event actually happened
}
```

### InteractionBatchPayload

```json
{
  "events": "[InteractionEventItem]"   // 1–200 events per request
}
```

### InteractionBatchResult

```json
{
  "accepted": "int",   // events stored
  "dropped":  "int"    // events silently ignored (stale, invalid post_id)
}
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

Upload each image individually. Collect the returned `image_url` values into the `image_urls` list in `PostCreate`. Images must exist in storage before creating a post.

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
Fetch a single post. Records a view (once per profile — second open of the same post triggers a **revisit** signal which is the strongest taste signal at +6.0). Marks the post as seen in the recommendation engine unconditionally.
**Response `200`:** `PostResponse` | **Errors:** `404`

#### `PATCH /posts/{post_id}`
Update own post. `is_closed` not editable here.
**Response `200`:** `PostResponse` | **Errors:** `403`, `404`

#### `DELETE /posts/{post_id}`
Delete own post. Cascades to all interactions. Removes storage images. Removes from recommendation index.
**Response `204`** | **Errors:** `403`, `404`

---

### Interactions

#### `POST /posts/{post_id}/like`
Toggle like. On like: updates taste profile (category + commodity + author affinity).
No taste update on unlike.
**Response `200`:** `{ "liked": bool, "like_count": int }` | **Errors:** `404`

#### `GET /posts/{post_id}/comments`
Oldest first. **Query:** `limit`, `offset`. **Response `200`:** `CommentResponse[]` | **Errors:** `404`

#### `POST /posts/{post_id}/comments`
Adds a comment and updates taste profile (category + commodity + author affinity).
**Body:** `{ "content": string }`. **Response `201`:** `CommentResponse` | **Errors:** `403` (disabled), `404`, `422`

#### `DELETE /posts/{post_id}/comments/{comment_id}`
Author only. **Response `204`** | **Errors:** `403`, `404`

#### `POST /posts/{post_id}/share`
Not idempotent — each call increments `share_count` and updates taste profile.
**Response `200`:** `{ "share_count": int }` | **Errors:** `404`

#### `POST /posts/{post_id}/save`
Toggle save. On save: updates taste profile (category + commodity + author affinity — strongest persistent signal at +5.0).
No taste update on unsave.
**Response `200`:** `{ "saved": bool }` | **Errors:** `404`

#### `POST /posts/{post_id}/close`
Toggle `is_closed` on a Deal post. Owner only. Closing removes post from recommendation pool; reopening re-indexes it.
**Response `200`:** `{ "is_closed": bool }` | **Errors:** `403`, `404`

---

## Interaction Batch Endpoint

### `POST /posts/interactions/batch`

Accepts a batch of high-volume behavioural events from the client. This is the primary signal source for the personalisation engine.

**Request:** `InteractionBatchPayload`

**Response `200`:** `InteractionBatchResult`

**Errors:** `422` — invalid `event_type`, missing `value_ms` on a dwell event, empty batch, batch exceeds 200 events

---

### Event Types

| `event_type` | `value_ms` | Triggered when |
|--------------|------------|----------------|
| `impression` | — | Post enters the viewport (≥ 50% visible) |
| `dwell` | **required** | Post exits the viewport — measure time it was visible |
| `open_read_more` | — | User taps "Read more" / expands the caption |
| `open_carousel` | — | User taps or swipes into the image carousel |
| `open_comments` | — | User opens the comments panel |
| `link_click` | — | User taps an external `source_url` link |

`revisit` is server-generated and must not be sent by the client.

---

### Dwell Signal Buckets

The server classifies `value_ms` automatically. Send the raw millisecond count — do not pre-classify.

| `value_ms` | Classified as | Effect on taste |
|------------|---------------|----------------|
| < 2 000 ms | bounce | **Negative** (−0.5) on category + commodity |
| 2 000 – 8 000 ms | short | Weak positive (+0.5) on category + commodity |
| 8 000 – 30 000 ms | medium | Medium positive (+2.0) on category + commodity + author |
| ≥ 30 000 ms | long | Strong positive (+3.5) on category + commodity + author |
| ≥ **3 000 ms** | — | Post auto-marked **seen** (excluded from feed for 30 days) |
| > 300 000 ms | — | Server stores 300 000 (5-minute cap applied silently) |

---

### Validation Rules

| Rule | Behaviour |
|------|-----------|
| `event_type` not in the valid set | `422` — entire batch rejected |
| `event_type = "dwell"` with no `value_ms` | `422` — entire batch rejected |
| `occurred_at` more than 2 hours in the past | Event silently dropped (counted in `dropped`) |
| `post_id` does not exist | Event silently dropped |
| Batch > 200 events | `422` — entire batch rejected |
| Batch is empty | `422` |

---

### Batching Strategy

```
During a scroll session:
  - Record "impression" when a post enters the viewport
  - Start dwell timer; stop and record "dwell" when post leaves viewport
  - Record open_* and link_click immediately (but still buffer into batch)

Flush the buffer when:
  - App goes to background / tab loses focus
  - User navigates away from the feed screen
  - Buffer reaches ~50 events
  - 30 seconds of continuous scroll idle (safety flush)

Timestamp rules:
  - occurred_at must be the actual time of the event, not the flush time
  - Use UTC with timezone: "2026-06-08T10:22:31Z"
  - Events older than 2 hours are silently dropped — do not hold buffers longer
```

---

### Signal Weight Reference

| Signal | Triggered by | Positive Δ | Negative Δ | Dimensions updated |
|--------|-------------|-----------|-----------|-------------------|
| impression | batch | 0.1 | — | category |
| dwell bounce | batch (job) | — | 0.5 | category, commodity |
| dwell short | batch (job) | 0.5 | — | category, commodity |
| dwell medium | batch (job) | 2.0 | — | category, commodity, author |
| dwell long | batch (job) | 3.5 | — | category, commodity, author |
| open_read_more | batch | 1.5 | — | category |
| open_carousel | batch | 1.0 | — | category |
| open_comments | batch | 1.5 | — | category |
| link_click | batch | 2.0 | — | category |
| like | `/like` | 3.0 | — | category, commodity, author |
| save | `/save` | 5.0 | — | category, commodity, author |
| share | `/share` | 4.0 | — | category, commodity, author |
| comment | `/comments` | 4.0 | — | category, commodity, author |
| revisit | server (on 2nd open) | 6.0 | — | category, commodity, author |
| repeated ignore | server (daily job) | — | 1.0 | category, commodity |

Author dimension is only updated when the signal's positive delta ≥ 2.0 **and** the post author is not the viewer.

---

### Negative Signals — What the Frontend Must NOT Do

The system has no explicit negative feedback mechanism. **Do not add a "not interested", "hide", or "dislike" button.** All negative signals are inferred server-side:

| Inferred negative | How detected | Frontend requirement |
|------------------|--------------|---------------------|
| Quick scroll-past | `dwell_ms < 2000` in a batch event | Send all dwell events — including very short ones |
| Repeated ignore | 5+ impressions on the same post, zero engagement | Send all impression events accurately |

The accuracy of negative learning depends entirely on honest impression and dwell reporting.

---

## Recommendation Feed

### `GET /posts/recommendation/feed`

Returns a personalised feed. Each call is stateless — the pipeline re-evaluates from scratch using the current seen-post set as the exclusion cursor.

**Query params:**

| param | type | default | range | description |
|-------|------|---------|-------|-------------|
| `limit` | int | 25 | 1–50 | number of posts to return |

**Response `200`:** `FeedResponse`

**Errors:** `404` profile not found

---

### Scoring Pipeline

```
1. Exclude posts seen in the last 30 days
2. ANN retrieval: hot → warm → cold (stops when pool ≥ 80 candidates)
3. Popular posts appended (top 30 by velocity score, filtered by user's commodity)
4. Fresh pool guarantee: posts < 4 h old injected with actual similarity scores
5. Rerank each candidate (see formula below)
6. Diversity filter: max 8 per category, max 3 per author
7. Return top `limit` posts
```

### Reranking Formula

```
final_score =
    vec_score              × (ANN cosine similarity — commodity/role/geo match)
    category_weight        × (learned taste, decayed, confidence-blended)
    commodity_multiplier   × (commodity affinity: 1.0–1.3×)
    (1 + engagement)       × (saves×3 + comments×2 + likes, log-compressed, [1.0–2.0])
    freshness_boost        × (exponential decay from publish time)
    social_or_affinity       (1.5× followed | 1.0–1.2× learned author affinity)
```

**Freshness boost:**
```
freshness = 1.0 + 0.4 × e^(−age_hours / 8)

age = 0 h  → 1.40×    age = 6 h  → 1.19×
age = 2 h  → 1.31×    age = 12 h → 1.09×
age = 4 h  → 1.24×    age = 48 h → ≈1.00×
```

**Commodity multiplier:**
```
1.0  — no commodity affinity data
1.0–1.3 — proportional to commodity taste score relative to user's strongest commodity
```

**Author signal:**
```
Followed author   → 1.5× (social boost — existing)
Non-followed author with engagement history → 1.0–1.2× (learned affinity)
Unknown author    → 1.0× (no effect)
```

**Category weight:**
Learned from all interactions, subject to ~30-day exponential decay. New users are blended with role-seeded defaults until 20 interactions are accumulated (Trader / Broker / Exporter presets).

---

### `has_more` Semantics

- `true` — batch is full (`len(posts) == limit`); unseen posts likely remain
- `false` — batch is smaller than `limit`; pool is exhausted for the current seen set

---

## Infinite Feed Flow

```
1. GET /feed?limit=25
   → 25 FeedPostCards, has_more: true

2. User scrolls. Frontend buffers events.

3. POST /interactions/batch  {events: [impressions, dwells, opens...]}
   → { accepted: 22, dropped: 0 }
   (server auto-marks posts with dwell >= 3 s as seen)

4. GET /feed?limit=25
   → next 25 posts (auto-seen posts from step 3 are excluded)

5. Repeat until has_more: false
```

**Key rules:**
- Seen-post exclusion is driven by dwell events (≥ 3 000 ms) and `GET /posts/{id}` opens
- `POST /posts/recommendation/seen` is deprecated — do not call it
- Refreshing the feed without sending dwell events returns the same posts — intended behaviour
- A post seen 31+ days ago becomes eligible again on the next feed call
- New posts published between feed calls are immediately eligible

---

### ~~`POST /posts/recommendation/seen`~~ — Deprecated

This endpoint is a **no-op shim** kept for backward compatibility with older clients. Do not call it from new code. Seen-post recording now happens automatically:
- Via `POST /posts/interactions/batch` — any `dwell` event with `value_ms >= 3000`
- Via `GET /posts/{post_id}` — unconditional on post open

---

### Background Jobs (internal / admin)

#### `POST /posts/recommendation/jobs/expiry`
Ages hot→warm→cold, soft-expires past-expiry posts, hard-deletes cold posts > 30 days.

#### `POST /posts/recommendation/jobs/popular-sync`
Recomputes velocity scores. Replaces `popular_posts` table.

#### `POST /posts/interactions/jobs/taste-update`
Manually triggers one batch of the dwell taste update job (runs automatically every 15 min).

#### `POST /posts/interactions/jobs/ignore-detect`
Manually triggers the repeated-ignore detection job (runs automatically daily at 03:00 IST).

All return: `{ "status": "ok", "details": { ... } }`

---

## Seen Post Behaviour

| Event | Seen recorded |
|-------|---------------|
| `dwell` event with `value_ms >= 3000` in batch | Yes — at batch accept time |
| `GET /posts/{post_id}` (open post) | Yes — unconditionally |
| Post appears in feed, no dwell event sent | No — reappears on next feed call |
| `POST /posts/recommendation/seen` | No-op — deprecated |
| Seen entry older than 30 days | Expired — post becomes eligible again |

---

## Location Behaviour

| Scenario | Geo used in recommendation |
|----------|---------------------------|
| Post has `latitude` + `longitude` | Post coordinates |
| Post has only `location_name` | Author's business coordinates |
| No location set | Author's business coordinates |

`location_name` in `FeedPostCard` is pre-built by the server: `post.location_name` if set, else `"city, state"` from the author's business profile.

---

## Category Expiry (Recommendation Index)

Posts are automatically removed from the recommendation index after:

| Category | Expiry |
|----------|--------|
| Market Update | 2 days |
| Deal / Requirement | 7 days |
| Discussion | 14 days |
| Knowledge | 90 days |

Expired posts no longer appear in the recommendation feed. They remain accessible via direct link or profile page.

---

## Business Rules

1. `deal_details` required when `category_id == 4`, ignored for all other categories.
2. `is_closed` only via `POST /{id}/close`, not PATCH.
3. View counted once per profile (unique constraint on `post_views`). A second open generates a **revisit** signal (+6.0 taste) automatically.
4. `like`, `save`, `comment`, `share` all update the persistent taste profile (category + commodity + author). The author dimension requires signal strength ≥ 2.0 and excludes self-interaction.
5. `target_roles: null` = all roles. `[1,2,3]` = restricted visibility.
6. Each image must be uploaded via `/upload-image` before referencing its URL in `PostCreate.image_urls`.
7. `latitude` + `longitude` must both be provided together — one alone has no effect on recommendation scoring.
8. Feed is stateless — no server-side session or delivery state between calls.
9. `has_more: false` means the pool is exhausted for the current seen set. New posts published after this point become eligible on the next call.
10. Dwell events with `value_ms < 2000` are a **negative** taste signal. Send them accurately — omitting short dwells degrades personalisation quality.
11. Impression events must be sent for every post rendered in the viewport. 5+ impressions on the same post with zero engagement trigger a server-side repeated-ignore downrank (daily job).
12. All `occurred_at` timestamps must be UTC. Events older than 2 hours at the time the batch is received are silently dropped.
