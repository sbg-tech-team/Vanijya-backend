# Post Module — API Contract v1

**Date:** 2026-05-21  
**Status:** Updated (post cleanup session)  
**Base URL:** `/posts`  
**Auth:** All endpoints require a valid JWT. The backend resolves `profile_id` from the token automatically unless noted otherwise.

---

## Reference Data

### Post Categories (fixed, seeded)

| id | name |
|----|------|
| 1 | Market Update |
| 2 | Knowledge |
| 3 | Discussion |
| 4 | Deal / Requirement |

### Commodities (foreign key — `commodities` table)

| id | name |
|----|------|
| 1 | Rice |
| 2 | Cotton |
| 3 | Sugar |

### Target Roles (for visibility filtering)

| id | role |
|----|------|
| 1 | Trader |
| 2 | Broker |
| 3 | Farmer |

### Price Types

| value | meaning |
|-------|---------|
| `"fixed"` | Fixed price deal |
| `"negotiable"` | Price open to negotiation |

---

## Shared Response Envelope

All endpoints (except 204 No Content) wrap their payload in:

```json
{
  "status": "success",
  "message": "...",
  "data": { ... }
}
```

---

## Image Upload Flow (3 steps)

Images must be uploaded before creating a post. This is a pre-signed URL flow.

### Step 1 — Get signed upload URL

```
POST /posts/upload-image?content_type=image/jpeg
```

**Query params:**

| param | type | required | values |
|-------|------|----------|--------|
| `content_type` | string | yes | `image/jpeg` \| `image/png` \| `image/webp` |

**Response `data`:**
```json
{
  "upload_url": "https://...",
  "image_url": "https://..."
}
```

### Step 2 — PUT image bytes

`PUT {upload_url}` — direct to storage, not through the API. Set `Content-Type` header to the same value sent in step 1.

### Step 3 — Use `image_url` in `POST /posts/`

Pass the `image_url` from step 1 in the post create body.

**Errors:**

| status | detail |
|--------|--------|
| 400 | Upload URL generation failed |
| 503 | Storage unavailable |

---

## Endpoints

---

### POST `/posts/` — Create post

**Status:** 201

**Request body:**

```json
{
  "category_id": 1,
  "commodity_id": 1,
  "title": "string (required, non-empty)",
  "caption": "string (required, non-empty)",
  "is_public": true,
  "target_roles": null,
  "allow_comments": true,
  "image_url": null,

  // Required only when category_id == 4 (Deal/Requirement)
  "grain_type_size": "Fine",
  "commodity_quantity_min": 100.0,
  "commodity_quantity_max": 500.0,
  "price_type": "fixed"
}
```

**Field rules:**

| field | type | default | notes |
|-------|------|---------|-------|
| `category_id` | int | — | required; 1–4 |
| `commodity_id` | int | — | required |
| `title` | string | — | required; stripped of whitespace |
| `caption` | string | — | required; stripped of whitespace |
| `is_public` | bool | `true` | `false` = followers only |
| `target_roles` | int[] \| null | `null` | null = visible to all roles |
| `allow_comments` | bool | `true` | |
| `image_url` | string \| null | `null` | use upload flow above |
| `grain_type_size` | string \| null | `null` | required if `category_id == 4` |
| `commodity_quantity_min` | float \| null | `null` | required if `category_id == 4` |
| `commodity_quantity_max` | float \| null | `null` | required if `category_id == 4` |
| `price_type` | `"fixed"` \| `"negotiable"` \| null | `null` | required if `category_id == 4` |

**Response `data`:** [`PostResponse`](#postresponse-object)

**Errors:**

| status | detail |
|--------|--------|
| 400 | Validation error (missing deal fields, empty caption, etc.) |
| 400 | Image upload error |
| 503 | Storage unavailable |

---

### GET `/posts/` — General feed

Returns posts visible to the current user (public posts + following).

**Query params:**

| param | type | default |
|-------|------|---------|
| `limit` | int | 20 |
| `offset` | int | 0 |

**Response `data`:** `PostResponse[]`

---

### GET `/posts/mine` — My posts

Returns all posts created by the current user.

**Query params:**

| param | type | default |
|-------|------|---------|
| `limit` | int | 20 |
| `offset` | int | 0 |

**Response `data`:** `PostResponse[]`

---

### GET `/posts/following` — Following feed

Returns posts from profiles the current user follows.

**Query params:**

| param | type | default |
|-------|------|---------|
| `limit` | int | 20 |
| `offset` | int | 0 |

**Response `data`:** `PostResponse[]`

---

### GET `/posts/saved` — Saved posts

Returns posts the current user has saved.

**Query params:**

| param | type | default |
|-------|------|---------|
| `limit` | int | 20 |
| `offset` | int | 0 |

**Response `data`:** `PostResponse[]`

---

### GET `/posts/{post_id}` — Get single post

**Path params:** `post_id: int`

**Response `data`:** [`PostResponse`](#postresponse-object)

**Errors:**

| status | detail |
|--------|--------|
| 404 | Post not found |

---

### PATCH `/posts/{post_id}` — Update post

Only the post owner can update. All fields optional.

**Path params:** `post_id: int`

**Request body:**

```json
{
  "title": "updated title",
  "caption": "updated text",
  "image_url": "https://...",
  "is_public": false,
  "target_roles": [1, 2],
  "allow_comments": false,
  "grain_type_size": "Coarse",
  "commodity_quantity_min": 200.0,
  "commodity_quantity_max": 800.0,
  "price_type": "negotiable"
}
```

**Response `data`:** [`PostResponse`](#postresponse-object)

**Errors:**

| status | detail |
|--------|--------|
| 403 | Not the post owner |
| 404 | Post not found |

---

### DELETE `/posts/{post_id}` — Delete post

Only the post owner can delete.

**Path params:** `post_id: int`

**Response:** 204 No Content

**Errors:**

| status | detail |
|--------|--------|
| 403 | Not the post owner |
| 404 | Post not found |

---

### POST `/posts/{post_id}/like` — Toggle like

Likes if not liked; unlikes if already liked.

**Path params:** `post_id: int`

**Response `data`:**

```json
{
  "liked": true,
  "like_count": 42
}
```

**Errors:**

| status | detail |
|--------|--------|
| 404 | Post not found |

---

### GET `/posts/{post_id}/comments` — Get comments

**Path params:** `post_id: int`

**Query params:**

| param | type | default |
|-------|------|---------|
| `limit` | int | 20 |
| `offset` | int | 0 |

**Response `data`:** [`CommentResponse[]`](#commentresponse-object)

**Errors:**

| status | detail |
|--------|--------|
| 404 | Post not found |

---

### POST `/posts/{post_id}/comments` — Add comment

**Status:** 201

**Path params:** `post_id: int`

**Request body:**

```json
{
  "content": "string (required, non-empty)"
}
```

**Response `data`:** [`CommentResponse`](#commentresponse-object)

**Errors:**

| status | detail |
|--------|--------|
| 403 | Comments disabled on this post |
| 404 | Post not found |

---

### DELETE `/posts/{post_id}/comments/{comment_id}` — Delete comment

Only the comment owner can delete.

**Path params:** `post_id: int`, `comment_id: int`

**Response:** 204 No Content

**Errors:**

| status | detail |
|--------|--------|
| 403 | Not the comment owner |
| 404 | Comment not found |

---

### POST `/posts/{post_id}/share` — Record share

Records a share event and increments `share_count`. Intended to be called when the user shares a post externally.

**Path params:** `post_id: int`

**Response `data`:**

```json
{
  "share_count": 10
}
```

**Errors:**

| status | detail |
|--------|--------|
| 404 | Post not found |

---

### POST `/posts/{post_id}/save` — Toggle save

Saves if not saved; unsaves if already saved.

**Path params:** `post_id: int`

**Response `data`:**

```json
{
  "saved": true
}
```

**Errors:**

| status | detail |
|--------|--------|
| 404 | Post not found |

---

## Recommendation Endpoints

Base: `/posts/recommendation`

---

### GET `/posts/recommendation/feed` — Recommended feed

Returns a ranked list of recommended post IDs with scores for the given profile.

> **Note:** This endpoint takes `profile_id` as a query param — it does NOT read from the auth token.

**Query params:**

| param | type | required |
|-------|------|----------|
| `profile_id` | int | yes |

**Response (direct array, no envelope):**

```json
[
  { "post_id": 101, "score": 0.87 },
  { "post_id": 204, "score": 0.74 }
]
```

**Errors:**

| status | detail |
|--------|--------|
| 404 | Profile not found / no taste profile |

---

### POST `/posts/recommendation/jobs/expiry` — Trigger expiry job

Internal/admin use. Migrates post embeddings across hot/warm/cold partitions and expires stale posts.

**Response:**

```json
{ "status": "ok", "details": { ... } }
```

---

### POST `/posts/recommendation/jobs/popular-sync` — Trigger popular-posts sync

Internal/admin use. Recalculates velocity scores for trending posts.

**Response:**

```json
{ "status": "ok", "details": { ... } }
```

---

## Response Object Shapes

### PostResponse object

```json
{
  "id": 1,
  "profile_id": 42,
  "category_id": 4,
  "commodity_id": 1,
  "caption": "Looking for 500 MT of fine rice",
  "image_url": "https://...",
  "is_public": true,
  "target_roles": [1, 2],
  "allow_comments": true,

  // Deal fields (non-null only when category_id == 4)
  "grain_type_size": "Fine",
  "commodity_quantity_min": 100.0,
  "commodity_quantity_max": 500.0,
  "price_type": "fixed",

  // Other field (non-null only when category_id == 5)
  "other_description": null,

  // Counters
  "view_count": 120,
  "like_count": 34,
  "comment_count": 8,
  "share_count": 5,

  // Viewer state (relative to requesting profile)
  "is_liked": false,
  "is_saved": true,

  "created_at": "2026-05-20T10:30:00Z"
}
```

> **Gap noted:** The DB model has a `save_count` column but `PostResponse` does not expose it. To be addressed in cleanup.

### CommentResponse object

```json
{
  "id": 7,
  "post_id": 1,
  "profile_id": 99,
  "content": "Great deal!",
  "created_at": "2026-05-20T11:00:00Z"
}
```

---

## Known Issues / Gaps (to address in this session)

1. **`save_count` missing from `PostResponse`** — field exists on the DB model but is not serialized.
2. **Recommendation feed bypasses auth** — `GET /posts/recommendation/feed` takes `profile_id` as a query param instead of reading from the JWT, inconsistent with every other endpoint.
3. **No pagination metadata** — feed endpoints return bare arrays with no `total` count or `has_more` flag.
4. **`PostUpdate` allows changing `category_id`** — not currently blocked, could create inconsistent category-specific field state.
5. **Comment ownership check** — `add_comment` raises `PostForbiddenError` (403) when comments are disabled; the error name is misleading (should be something like `CommentsDisabledError`).
