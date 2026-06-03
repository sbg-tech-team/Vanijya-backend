# Post Module API Contract — v4

> Reflects codebase state as of 2026-06-03.
>
> **Changes from v3:**
> - `Post` gains four new optional fields: `source_url`, `location_name`, `latitude`, `longitude`.
> - All four fields added to `PostCreate`, `PostUpdate`, and `PostResponse`.
> - Recommendation engine now uses the post's own `latitude/longitude` when provided, falling back to the author's business location.
> - `POST /posts/{post_id}/close` — 403 now also covers missing `deal_details` row.

---

## Base URL

```
/posts
```

All endpoints require a valid JWT (`Authorization: Bearer <token>`). The token is resolved to a `profile_id` server-side — clients never send `profile_id` explicitly.

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
All fields optional. `is_closed` is **not** editable here — use `POST /{id}/close`.

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
  "target_roles":   "[int]?",          // null=all roles  [1/2/3]=specific roles
  "allow_comments": "bool",            // default: true
  "image_url":      "string?",         // from /upload-image step
  "source_url":     "string?",         // link to external information source
  "location_name":  "string?",         // human-readable place label (city / market)
  "latitude":       "float?",          // overrides author location in recommendation
  "longitude":      "float?",          // overrides author location in recommendation
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
  "created_at":    "datetime"
}
```

### PostAuthorResponse
Embedded inside `FeedPostCard`.

```json
{
  "profile_id":           "int",
  "name":                 "string",
  "role_id":              "int",       // 1=Trader  2=Broker  3=Exporter
  "avatar_url":           "string?",
  "city":                 "string?",
  "state":                "string?",
  "is_user_verified":     "bool",
  "is_business_verified": "bool"
}
```

### FeedPostCard
Returned by `GET /posts/recommendation/feed`. One card = one recommended post, fully hydrated.

```json
{
  "post":   "PostResponse",
  "author": "PostAuthorResponse",
  "score":  "float"
}
```

---

## Endpoints

### Image Upload

#### `POST /posts/upload-image`

Get a presigned S3 URL to upload a post image before creating the post.

**Query params:**
| param        | type   | required |
|--------------|--------|----------|
| content_type | string | yes — `image/jpeg` \| `image/png` \| `image/webp` |

**Response `200`:**
```json
{
  "upload_url":   "string",
  "image_url":    "string",
  "content_type": "string"
}
```

**Flow:** Call this → PUT image bytes to `upload_url` → include `image_url` in `POST /posts/`.

**Errors:**
| status | reason |
|--------|--------|
| 400 | unsupported content_type |

---

### Posts CRUD

#### `POST /posts/`

Create a post.

**Body:** `PostCreate`

**Response `201`:** `PostResponse`

**Notes:**
- If `latitude` and `longitude` are provided, the post's geo vector in the recommendation engine uses the post location instead of the author's business location.
- If only `location_name` is provided without coordinates, it is stored for display but does not affect the recommendation vector.

**Errors:**
| status | reason |
|--------|--------|
| 400 | image not found in storage / wrong bucket / wrong profile |
| 422 | title/caption empty, deal_details missing for category 4, invalid price_type/quantity_unit |
| 503 | storage verification temporarily unavailable |

---

#### ~~`GET /posts/`~~ *(disabled — no active use case)*

Chronological feed of all active posts. Commented out pending an Explore/Browse screen design.

---

#### `GET /posts/mine`

Posts created by the authenticated profile, newest first.

**Query params:** `limit` (default 20), `offset` (default 0)

**Response `200`:** `PostResponse[]`

---

#### `GET /posts/following`

Posts from followed users, created within the last 7 days, newest first.

**Query params:** `limit`, `offset`

**Response `200`:** `PostResponse[]`

---

#### `GET /posts/saved`

Posts saved by the authenticated profile, newest save first.

**Query params:** `limit`, `offset`

**Response `200`:** `PostResponse[]`

---

#### `GET /posts/{post_id}`

Fetch a single post.

**Side effects:**
- Records a view (idempotent per profile — counted once via unique constraint).
- Marks the post as seen in the recommendation engine (will not reappear in feed for 30 days).

**Response `200`:** `PostResponse`

**Errors:**
| status | reason |
|--------|--------|
| 404 | post not found |

---

#### `PATCH /posts/{post_id}`

Update a post. Only the owner can edit. `deal_details` fields are updated individually (only non-null fields applied). `is_closed` cannot be changed here.

**Body:** `PostUpdate`

**Response `200`:** `PostResponse`

**Errors:**
| status | reason |
|--------|--------|
| 403 | not the post owner |
| 404 | post not found |

---

#### `DELETE /posts/{post_id}`

Delete a post. Cascade deletes likes, comments, shares, saves, deal_details. Soft-deletes the recommendation embedding. Deletes the S3 image if present.

**Response `204`:** no body

**Errors:**
| status | reason |
|--------|--------|
| 403 | not the post owner |
| 404 | post not found |

---

### Likes

#### `POST /posts/{post_id}/like`

Toggle like on/off.

**Response `200`:**
```json
{ "liked": "bool", "like_count": "int" }
```

**Errors:**
| status | reason |
|--------|--------|
| 404 | post not found |

---

### Comments

#### `GET /posts/{post_id}/comments`

Fetch comments, oldest first.

**Query params:** `limit`, `offset`

**Response `200`:**
```json
[{
  "id":         "int",
  "post_id":    "int",
  "profile_id": "int",
  "content":    "string",
  "created_at": "datetime"
}]
```

**Errors:**
| status | reason |
|--------|--------|
| 404 | post not found |

---

#### `POST /posts/{post_id}/comments`

Add a comment.

**Body:** `{ "content": "string" }`

**Response `201`:** `CommentResponse`

**Errors:**
| status | reason |
|--------|--------|
| 403 | comments disabled on this post |
| 404 | post not found |
| 422 | content is empty |

---

#### `DELETE /posts/{post_id}/comments/{comment_id}`

Delete a comment. Only the comment author can delete.

**Response `204`:** no body

**Errors:**
| status | reason |
|--------|--------|
| 403 | not the comment author |
| 404 | comment not found |

---

### Shares

#### `POST /posts/{post_id}/share`

Record an external share. Not idempotent — each call increments `share_count`.

**Response `200`:**
```json
{ "share_count": "int" }
```

**Errors:**
| status | reason |
|--------|--------|
| 404 | post not found |

---

### Saves

#### `POST /posts/{post_id}/save`

Toggle save on/off.

**Response `200`:**
```json
{ "saved": "bool" }
```

**Errors:**
| status | reason |
|--------|--------|
| 404 | post not found |

---

### Deal Close / Reopen

#### `POST /posts/{post_id}/close`

Toggle `is_closed` on a Deal/Requirement post. Only the post owner can call this.

- Closing: removes post from recommendation pool (`is_active=False` in embeddings).
- Reopening: re-indexes the post. Uses the post's own `latitude/longitude` if set, otherwise the author's business location.

**Response `200`:**
```json
{ "is_closed": "bool" }
```

**Errors:**
| status | reason |
|--------|--------|
| 403 | not the post owner |
| 403 | post is not category 4 (Deal/Requirement) |
| 403 | deal_details row is missing on this post |
| 404 | post not found |

---

## Recommendation Feed

### `GET /posts/recommendation/feed`

Returns a personalised feed of up to 25 posts. Each card includes full post data and author profile — no follow-up requests needed to render a feed card.

**Scoring factors:**
- **Vector similarity** — commodity, role, target roles, geo (post location if set, else author location), deal quantity
- **Taste weight** — based on the viewer's persistent category engagement history
- **Engagement** — weighted blend of saves (×3), comments (×2), likes (×1), log-normalised
- **Freshness** — 1.4× if < 2h old, 1.2× if < 6h, 1.0× otherwise
- **Social boost** — 1.5× if the post author is followed by the viewer

**Exclusions:** closed deals, posts seen in the last 30 days.

**Response `200`:** `FeedPostCard[]`

```json
[
  {
    "post": {
      "id": 42,
      "category_id": 4,
      "commodity_id": 1,
      "title": "Basmati available — 200 MT",
      "caption": "...",
      "source_url": null,
      "location_name": "Karnal Mandi",
      "latitude": 29.6857,
      "longitude": 76.9905,
      "deal_details": { "grain_type": "Basmati", "commodity_quantity": 200, ... },
      ...
    },
    "author": {
      "profile_id": 3,
      "name": "Ravi Kumar",
      "role_id": 1,
      "avatar_url": "https://...",
      "city": "Panipat",
      "state": "Haryana",
      "is_user_verified": true,
      "is_business_verified": false
    },
    "score": 0.3821
  }
]
```

**Errors:**
| status | reason |
|--------|--------|
| 404 | profile not found |

---

### `POST /posts/recommendation/seen`

Mark posts as seen. Frontend decides when a post qualifies as seen (scroll dwell, explicit open, etc.). Excluded from recommendation feed for 30 days.

> Opening a post via `GET /posts/{post_id}` also marks it as seen automatically.

**Body:**
```json
{ "post_ids": [42, 17, 93] }
```

**Response `204`:** no body

**Errors:**
| status | reason |
|--------|--------|
| 422 | post_ids is empty |

---

### Background Jobs (internal / admin)

#### `POST /posts/recommendation/jobs/expiry`
Ages hot → warm → cold partitions and deactivates expired posts.

#### `POST /posts/recommendation/jobs/popular-sync`
Recalculates velocity scores for the `popular_posts` fallback pool.

Both return:
```json
{ "status": "ok", "details": { ... } }
```

---

## Location Behaviour

| Scenario | Geo used in recommendation vector |
|---|---|
| Post has `latitude` + `longitude` | Post coordinates |
| Post has only `location_name` | Author's business coordinates |
| Post has no location fields | Author's business coordinates |

`location_name` is display-only — it appears in `PostResponse` but does not affect vector scoring. Only `latitude` and `longitude` affect the recommendation engine.

---

## Seen Post Behaviour

| Event | Seen recorded |
|---|---|
| `POST /posts/recommendation/seen` with `post_ids` | Yes — immediately |
| `GET /posts/{post_id}` (open post) | Yes — unconditionally |
| Post appears in feed, no signal sent | No — can reappear next feed load |

Seen entries expire after 30 days — posts resurface automatically after the window.

---

## Business Rules

1. `deal_details` is required when `category_id == 4`, ignored for all other categories.
2. `is_closed` can only be changed via `POST /{id}/close`, not via PATCH.
3. A view is counted at most once per profile per post (unique constraint on `post_views`).
4. `like` and `save` increment the persistent taste profile used to tune the recommendation feed.
5. `target_roles: null` means the post targets all roles. `[1,2,3]` restricts visibility.
6. Image must be uploaded to the posts bucket (via `/upload-image`) before referencing in `PostCreate`.
7. `latitude` and `longitude` must both be provided together — providing only one has no effect on recommendation scoring.
8. A deal post removed from the recommendation pool (closed or deleted) is not shown in feeds but remains accessible via direct `GET /posts/{id}`.
