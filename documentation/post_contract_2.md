# Post Module API Contract — v2

> Reflects codebase state as of 2026-05-25.
> Changes from v1: `title` added (required), flat deal fields moved to nested `deal_details` object, `save_count` added to response, `POST /{id}/close` endpoint added, "Other" category removed, recommendation feed now requires JWT.

---

## Base URL

```
/posts
```

All endpoints require a valid JWT (`Authorization: Bearer <token>`). The token is resolved to a `profile_id` server-side — clients never send `profile_id` explicitly.

---

## Post Categories

| id | name           |
|----|----------------|
| 1  | Market Update  |
| 2  | Knowledge      |
| 3  | Discussion     |
| 4  | Deal / Requirement |

---

## Schemas

### PostDealCreate
Required when `category_id == 4`.

```json
{
  "grain_type": "string",          // commodity variety e.g. "Basmati"
  "grain_size": "string",          // grade/measurement e.g. "8.22mm", "Fine"
  "commodity_quantity": "float",
  "quantity_unit": "string",       // "MT" | "quintal"
  "commodity_price": "float",
  "price_type": "string"           // "fixed" | "negotiable"
}
```

### PostDealUpdate
All fields optional. `is_closed` is **not** editable here — use `POST /{id}/close`.

```json
{
  "grain_type": "string?",
  "grain_size": "string?",
  "commodity_quantity": "float?",
  "quantity_unit": "string?",      // "MT" | "quintal"
  "commodity_price": "float?",
  "price_type": "string?"          // "fixed" | "negotiable"
}
```

### PostDealResponse

```json
{
  "grain_type": "string",
  "grain_size": "string",
  "commodity_quantity": "float",
  "quantity_unit": "string",
  "commodity_price": "float",
  "price_type": "string",
  "is_closed": "bool"
}
```

### PostCreate

```json
{
  "category_id": "int",            // 1–4, required
  "commodity_id": "int",           // 1=Rice 2=Cotton 3=Sugar
  "title": "string",               // required, non-empty
  "caption": "string",             // required, non-empty
  "is_public": "bool",             // default: true
  "target_roles": "[int]?",        // null=all roles, [1/2/3]=specific roles
  "allow_comments": "bool",        // default: true
  "image_url": "string?",          // from /upload-image step
  "deal_details": "PostDealCreate?"// required if category_id == 4
}
```

### PostUpdate (PATCH — all fields optional)

```json
{
  "title": "string?",
  "caption": "string?",
  "image_url": "string?",
  "is_public": "bool?",
  "target_roles": "[int]?",
  "allow_comments": "bool?",
  "deal_details": "PostDealUpdate?"
}
```

### PostResponse

```json
{
  "id": "int",
  "profile_id": "int",
  "category_id": "int",
  "commodity_id": "int",
  "title": "string",
  "caption": "string",
  "image_url": "string?",
  "is_public": "bool",
  "target_roles": "[int]?",
  "allow_comments": "bool",
  "deal_details": "PostDealResponse?",  // null for non-deal posts
  "view_count": "int",
  "like_count": "int",
  "comment_count": "int",
  "share_count": "int",
  "save_count": "int",
  "is_liked": "bool",
  "is_saved": "bool",
  "created_at": "datetime"
}
```

---

## Endpoints

### Image Upload

#### `POST /posts/upload-image`

Get a presigned S3 URL to upload a post image before creating the post.

**Query params:**
| param | type | required |
|-------|------|----------|
| content_type | string | yes — `image/jpeg` \| `image/png` \| `image/webp` |

**Response `200`:**
```json
{
  "upload_url": "string",
  "image_url": "string",
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

Create a post. If `image_url` is provided the image must already be uploaded (verified server-side).

**Body:** `PostCreate`

**Response `201`:** `PostResponse`

**Errors:**
| status | reason |
|--------|--------|
| 400 | image not found in storage / wrong bucket / wrong profile |
| 422 | validation — title/caption empty, deal_details missing for category 4, invalid price_type/quantity_unit |
| 503 | storage verification temporarily unavailable |

---

#### `GET /posts/`

Chronological feed of all active posts (paginated).

**Query params:** `limit` (default 20), `offset` (default 0)

**Response `200`:** `PostResponse[]`

---

#### `GET /posts/mine`

Posts created by the authenticated profile.

**Query params:** `limit`, `offset`

**Response `200`:** `PostResponse[]`

---

#### `GET /posts/following`

Posts from followed users, created within the last 7 days.

**Query params:** `limit`, `offset`

**Response `200`:** `PostResponse[]`

---

#### `GET /posts/saved`

Posts saved by the authenticated profile, newest save first.

**Query params:** `limit`, `offset`

**Response `200`:** `PostResponse[]`

---

#### `GET /posts/{post_id}`

Fetch a single post. Records a view (idempotent per profile — counted once).

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

Delete a post (cascade deletes all likes, comments, shares, saves, deal_details). Also soft-deletes the recommendation embedding. Deletes the S3 image if present.

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
  "id": "int",
  "post_id": "int",
  "profile_id": "int",
  "content": "string",
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

**Body:**
```json
{ "content": "string" }
```

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
- Reopening: re-indexes the post into the recommendation pool.

**Response `200`:**
```json
{ "is_closed": "bool" }
```

**Errors:**
| status | reason |
|--------|--------|
| 403 | not the post owner, or post is not category 4 |
| 404 | post not found |

---

## Recommendation Feed

### `GET /posts/recommendation/feed`

Returns a personalised feed of up to 25 posts scored by vector similarity, taste profile, engagement, freshness, and social graph. Closed deals are excluded. Seen posts (last 30 days) are excluded.

**Response `200`:**
```json
[{ "post_id": "int", "score": "float" }]
```

> Returns `post_id` and score only. Fetch full post data via `GET /posts/{post_id}` as needed.

**Errors:**
| status | reason |
|--------|--------|
| 404 | profile not found |

---

### Background Jobs (internal / admin)

#### `POST /posts/recommendation/jobs/expiry`
Ages hot → warm → cold partitions and deactivates expired posts.

#### `POST /posts/recommendation/jobs/popular-sync`
Recalculates velocity scores for the `popular_posts` table used as a fallback pool.

Both return:
```json
{ "status": "ok", "details": { ... } }
```

---

## Business Rules

1. `deal_details` is required when `category_id == 4`, forbidden (ignored) for all other categories.
2. `is_closed` can only be changed via `POST /{id}/close`, not via PATCH.
3. A view is counted at most once per profile per post (unique constraint).
4. `like` and `save` each trigger a taste profile event used to tune the recommendation feed.
5. `target_roles: null` means the post targets all roles. `[1,2,3]` restricts visibility to those roles.
6. Image must be uploaded to the posts bucket (via `/upload-image`) before referencing it in `PostCreate`.
