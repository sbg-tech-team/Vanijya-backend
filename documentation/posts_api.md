# Posts Module — API Documentation

**Base URL:** `https://vanijyaa-backend.onrender.com`  
**All responses follow the envelope format:**

```json
{
  "success": true,
  "message": "...",
  "data": { ... }
}
```

**All endpoints require `Authorization: Bearer <token>` header.**  
> The `profile_id` is derived from the JWT token — do not pass it as a query parameter.  
> See [auth_and_access_control.md](auth_and_access_control.md) for the full auth model.

---

## Reference Data (DB Seeded)

| Type | ID | Name |
|------|----|------|
| **Category** | 1 | Market Update |
| **Category** | 2 | Knowledge |
| **Category** | 3 | Discussion |
| **Category** | 4 | Deal / Requirement |
| **Category** | 5 | Other |
| **Commodity** | 1 | Rice |
| **Commodity** | 2 | Cotton |
| **Commodity** | 3 | Sugar |
| **Role** | 1 | Trader |
| **Role** | 2 | Broker |
| **Role** | 3 | Exporter |

---

## Table of Contents

1. [Upload Post Image](#1-upload-post-image)
2. [Create Post](#2-create-post)
3. [Get Feed](#3-get-feed)
4. [Get My Posts](#4-get-my-posts)
5. [Get Following Feed](#5-get-following-feed)
6. [Get Saved Posts](#6-get-saved-posts)
7. [Get Single Post](#7-get-single-post)
8. [Update Post](#8-update-post)
9. [Delete Post](#9-delete-post)
10. [Like / Unlike Post](#10-like--unlike-post)
11. [Get Comments](#11-get-comments)
12. [Add Comment](#12-add-comment)
13. [Delete Comment](#13-delete-comment)
14. [Share Post](#14-share-post)
15. [Save / Unsave Post](#15-save--unsave-post)
16. [Error Reference](#16-error-reference)

---

## Post Object (Full Response Shape)

Every endpoint that returns a post will include this shape inside `data`:

```json
{
  "id": 1,
  "profile_id": 3,
  "category_id": 1,
  "commodity_id": 2,
  "caption": "Cotton prices are up this week.",
  "image_url": null,
  "is_public": true,
  "target_roles": null,
  "allow_comments": true,
  "grain_type_size": null,
  "commodity_quantity_min": null,
  "commodity_quantity_max": null,
  "price_type": null,
  "other_description": null,
  "view_count": 14,
  "like_count": 3,
  "comment_count": 2,
  "share_count": 1,
  "is_liked": false,
  "is_saved": true,
  "created_at": "2026-04-17T10:30:00"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | int | Unique post ID |
| `profile_id` | int | Profile that created the post |
| `category_id` | int | 1–5 (see reference table above) |
| `commodity_id` | int | 1–3 (see reference table above) |
| `caption` | string | Post text content |
| `image_url` | string \| null | Optional image URL |
| `is_public` | bool | `true` = visible to all, `false` = followers only |
| `target_roles` | int[] \| null | `null` = all roles, or array like `[1, 3]` |
| `allow_comments` | bool | Whether comments are enabled |
| `grain_type_size` | string \| null | Filled only for category 4 |
| `commodity_quantity_min` | float \| null | Lower bound of trade range — only for category 4 |
| `commodity_quantity_max` | float \| null | Upper bound of trade range — only for category 4 |
| `price_type` | string \| null | `"fixed"` or `"negotiable"` — only for category 4 |
| `other_description` | string \| null | Filled only for category 5 |
| `view_count` | int | Unique profile views |
| `like_count` | int | Total likes |
| `comment_count` | int | Total comments |
| `share_count` | int | Total shares |
| `is_liked` | bool | Whether the requesting profile has liked this post |
| `is_saved` | bool | Whether the requesting profile has saved this post |
| `created_at` | datetime | ISO 8601 UTC timestamp |

---

## 1. Upload Post Image

**`POST /posts/upload-image?profile_id={profile_id}&content_type={content_type}`**

Generates a short-lived signed upload URL for storing a post image in Supabase Storage. Use this **before** creating the post. Images are uploaded directly from the client to Supabase — the backend never receives the file bytes.

### 3-Step Flow

```
Step 1 — POST /posts/upload-image   → get { upload_url, image_url }
Step 2 — PUT {upload_url}           → upload image bytes directly (Content-Type must match)
Step 3 — POST /posts/              → create post with image_url from Step 1
```

### Query Parameters

| Param | Type | Required | Notes |
|-------|------|----------|-------|
| `profile_id` | int | Yes | Your profile ID |
| `content_type` | string | Yes | `image/jpeg`, `image/png`, or `image/webp` |

### Response — `200 OK`

```json
{
  "success": true,
  "message": "Upload URL generated",
  "data": {
    "upload_url": "https://<project>.supabase.co/storage/v1/object/sign/post-images/3_abc123.jpg?token=...",
    "image_url": "https://<project>.supabase.co/storage/v1/object/public/post-images/3_abc123.jpg"
  }
}
```

| Field | Description |
|-------|-------------|
| `upload_url` | Signed PUT URL — send image bytes here with matching `Content-Type` header. Expires quickly. |
| `image_url` | Public URL to store in the post — pass this as `image_url` in `POST /posts/` |

### Step 2 — Client-side PUT

```http
PUT {upload_url}
Content-Type: image/jpeg

<binary image bytes>
```

### Errors

| Status | Reason |
|--------|--------|
| `400` | Unsupported `content_type` — must be `image/jpeg`, `image/png`, or `image/webp` |
| `503` | Supabase Storage unavailable |

---

## 2. Create Post

**`POST /posts/?profile_id={profile_id}`**

### Request Body

#### Standard Post (categories 1, 2, 3)

```json
{
  "category_id": 1,
  "commodity_id": 2,
  "caption": "Cotton market is very active this season.",
  "is_public": true,
  "allow_comments": true,
  "target_roles": null,
  "image_url": null
}
```

#### Deal / Requirement Post (category 4) — extra fields required

```json
{
  "category_id": 4,
  "commodity_id": 1,
  "caption": "Looking for 500 MT of basmati rice.",
  "is_public": true,
  "allow_comments": true,
  "grain_type_size": "Basmati Long Grain",
  "commodity_quantity_min": 200.0,
  "commodity_quantity_max": 500.0,
  "price_type": "negotiable"
}
```

#### Other Post (category 5) — extra field required

```json
{
  "category_id": 5,
  "commodity_id": 3,
  "caption": "Check this out.",
  "is_public": true,
  "allow_comments": true,
  "other_description": "This is a general update about our operations."
}
```

### Request Body Fields

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `category_id` | int | Yes | 1–5 |
| `commodity_id` | int | Yes | 1–3 |
| `caption` | string | Yes | Cannot be empty |
| `is_public` | bool | No | Default: `true` |
| `allow_comments` | bool | No | Default: `true` |
| `target_roles` | int[] \| null | No | Default: `null` (all roles) |
| `image_url` | string \| null | No | Default: `null` |
| `grain_type_size` | string | **Required if category 4** | — |
| `commodity_quantity_min` | float | **Required if category 4** | Lower bound in metric tonnes (MT) |
| `commodity_quantity_max` | float | **Required if category 4** | Upper bound in metric tonnes (MT) |
| `price_type` | string | **Required if category 4** | `"fixed"` or `"negotiable"` |
| `other_description` | string | **Required if category 5** | Cannot be empty |

### Response — `201 Created`

```json
{
  "success": true,
  "message": "Post created successfully",
  "data": {
    "id": 7,
    "profile_id": 3,
    "category_id": 1,
    "commodity_id": 2,
    "caption": "Cotton market is very active this season.",
    "image_url": null,
    "is_public": true,
    "target_roles": null,
    "allow_comments": true,
    "grain_type_size": null,
    "commodity_quantity": null,
    "price_type": null,
    "other_description": null,
    "view_count": 0,
    "like_count": 0,
    "comment_count": 0,
    "share_count": 0,
    "is_liked": false,
    "is_saved": false,
    "created_at": "2026-04-17T10:30:00"
  }
}
```

### Errors

| Status | Reason |
|--------|--------|
| `422` | Missing required fields, empty caption, invalid `price_type`, category 4 missing deal fields, category 5 missing `other_description` |

---

## 3. Get Feed

**`GET /posts/?profile_id={profile_id}&limit={limit}&offset={offset}`**

Returns all posts (newest first). View counts are NOT incremented by the feed — only by `GET /posts/{post_id}`.

### Query Parameters

| Param | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `profile_id` | int | Yes | — | Viewer's profile ID |
| `limit` | int | No | `20` | Max posts to return |
| `offset` | int | No | `0` | Pagination offset |

### Response — `200 OK`

```json
{
  "success": true,
  "message": "Feed fetched successfully",
  "data": [
    {
      "id": 7,
      "profile_id": 3,
      "category_id": 1,
      "commodity_id": 2,
      "caption": "Cotton market is very active this season.",
      "image_url": null,
      "is_public": true,
      "target_roles": null,
      "allow_comments": true,
      "grain_type_size": null,
      "commodity_quantity": null,
      "price_type": null,
      "other_description": null,
      "view_count": 0,
      "like_count": 0,
      "comment_count": 0,
      "share_count": 0,
      "is_liked": false,
      "is_saved": false,
      "created_at": "2026-04-17T10:30:00"
    }
  ]
}
```

> `data` is an array (may be empty `[]`).

---

## 4. Get My Posts

**`GET /posts/mine?profile_id={profile_id}&limit={limit}&offset={offset}`**

Returns only posts created by the given `profile_id`, newest first.

### Query Parameters

Same as [Get Feed](#3-get-feed).

### Response — `200 OK`

Same shape as Get Feed. `data` is an array of post objects.

---

## 5. Get Following Feed

**`GET /posts/following?profile_id={profile_id}&limit={limit}&offset={offset}`**

Returns posts from users that the given profile follows, filtered to the **last 7 days**, newest first. Only shows posts the viewer is allowed to see (`is_public: true` or targeted at viewer's role).

### Query Parameters

Same as [Get Feed](#3-get-feed).

### Response — `200 OK`

Same shape as Get Feed. `data` is an array of post objects (may be `[]` if not following anyone or no recent posts).

---

## 6. Get Saved Posts

**`GET /posts/saved?profile_id={profile_id}&limit={limit}&offset={offset}`**

Returns posts the profile has saved, ordered by most-recently-saved first.

### Query Parameters

Same as [Get Feed](#3-get-feed).

### Response — `200 OK`

Same shape as Get Feed. `data` is an array of post objects.

---

## 7. Get Single Post

**`GET /posts/{post_id}?profile_id={profile_id}`**

Fetches a single post. **Increments `view_count` by 1** (only once per profile — subsequent views by the same profile are ignored).

### Path Parameters

| Param | Type | Description |
|-------|------|-------------|
| `post_id` | int | ID of the post |

### Response — `200 OK`

```json
{
  "success": true,
  "message": "Post fetched successfully",
  "data": {
    "id": 7,
    "profile_id": 3,
    "category_id": 4,
    "commodity_id": 1,
    "caption": "Looking for 500 MT of basmati rice.",
    "image_url": null,
    "is_public": true,
    "target_roles": null,
    "allow_comments": true,
    "grain_type_size": "Basmati Long Grain",
    "commodity_quantity_min": 200.0,
    "commodity_quantity_max": 500.0,
    "price_type": "negotiable",
    "other_description": null,
    "view_count": 1,
    "like_count": 0,
    "comment_count": 0,
    "share_count": 0,
    "is_liked": false,
    "is_saved": false,
    "created_at": "2026-04-17T10:30:00"
  }
}
```

### Errors

| Status | Reason |
|--------|--------|
| `404` | Post not found |

---

## 8. Update Post

**`PATCH /posts/{post_id}?profile_id={profile_id}`**

Updates a post. Only the owner (`profile_id` must match `post.profile_id`) can update. All fields are optional — only send what you want to change.

### Request Body

```json
{
  "caption": "Updated caption text.",
  "allow_comments": false,
  "is_public": true,
  "grain_type_size": "Short Grain",
  "commodity_quantity_min": 100.0,
  "commodity_quantity_max": 300.0,
  "price_type": "fixed",
  "other_description": null,
  "image_url": null
}
```

| Field | Type | Notes |
|-------|------|-------|
| `caption` | string \| null | Cannot be empty string if provided |
| `image_url` | string \| null | — |
| `is_public` | bool \| null | — |
| `target_roles` | int[] \| null | — |
| `allow_comments` | bool \| null | — |
| `grain_type_size` | string \| null | — |
| `commodity_quantity_min` | float \| null | — |
| `commodity_quantity_max` | float \| null | — |
| `price_type` | string \| null | `"fixed"` or `"negotiable"` |
| `other_description` | string \| null | — |

### Response — `200 OK`

```json
{
  "success": true,
  "message": "Post updated successfully",
  "data": {
    "id": 7,
    "profile_id": 3,
    "category_id": 1,
    "commodity_id": 2,
    "caption": "Updated caption text.",
    "image_url": null,
    "is_public": true,
    "target_roles": null,
    "allow_comments": false,
    "grain_type_size": null,
    "commodity_quantity": null,
    "price_type": null,
    "other_description": null,
    "view_count": 1,
    "like_count": 0,
    "comment_count": 0,
    "share_count": 0,
    "is_liked": false,
    "is_saved": false,
    "created_at": "2026-04-17T10:30:00"
  }
}
```

### Errors

| Status | Reason |
|--------|--------|
| `404` | Post not found |
| `403` | `profile_id` does not own this post |
| `422` | Validation error (e.g. empty caption, invalid `price_type`) |

---

## 9. Delete Post

**`DELETE /posts/{post_id}?profile_id={profile_id}`**

Permanently deletes a post and all its likes, comments, shares, saves (cascade). Only the owner can delete.

### Response — `204 No Content`

No response body.

### Errors

| Status | Reason |
|--------|--------|
| `404` | Post not found |
| `403` | `profile_id` does not own this post |

---

## 10. Like / Unlike Post

**`POST /posts/{post_id}/like?profile_id={profile_id}`**

Toggles the like state. First call = like, second call = unlike. No request body needed.

### Response — `200 OK`

**After liking:**
```json
{
  "success": true,
  "message": "Like toggled",
  "data": {
    "liked": true,
    "like_count": 4
  }
}
```

**After unliking (calling again):**
```json
{
  "success": true,
  "message": "Like toggled",
  "data": {
    "liked": false,
    "like_count": 3
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `liked` | bool | Current like state for this profile |
| `like_count` | int | Updated total like count on the post |

### Errors

| Status | Reason |
|--------|--------|
| `404` | Post not found |

---

## 11. Get Comments

**`GET /posts/{post_id}/comments?profile_id={profile_id}&limit={limit}&offset={offset}`**

Returns comments on a post, ordered oldest first.

### Query Parameters

| Param | Type | Required | Default |
|-------|------|----------|---------|
| `profile_id` | int | Yes | — |
| `limit` | int | No | `20` |
| `offset` | int | No | `0` |

### Response — `200 OK`

```json
{
  "success": true,
  "message": "Comments fetched successfully",
  "data": [
    {
      "id": 12,
      "post_id": 7,
      "profile_id": 5,
      "content": "Very insightful, thanks!",
      "created_at": "2026-04-17T11:00:00"
    },
    {
      "id": 13,
      "post_id": 7,
      "profile_id": 3,
      "content": "Agreed, great update.",
      "created_at": "2026-04-17T11:05:00"
    }
  ]
}
```

### Errors

| Status | Reason |
|--------|--------|
| `404` | Post not found |

---

## 12. Add Comment

**`POST /posts/{post_id}/comments?profile_id={profile_id}`**

Adds a comment to a post.

### Request Body

```json
{
  "content": "Very insightful, thanks!"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `content` | string | Yes | Cannot be empty |

### Response — `201 Created`

```json
{
  "success": true,
  "message": "Comment added successfully",
  "data": {
    "id": 12,
    "post_id": 7,
    "profile_id": 5,
    "content": "Very insightful, thanks!",
    "created_at": "2026-04-17T11:00:00"
  }
}
```

### Errors

| Status | Reason |
|--------|--------|
| `404` | Post not found |
| `403` | Comments are disabled on this post (`allow_comments: false`) |
| `422` | Empty `content` |

---

## 13. Delete Comment

**`DELETE /posts/{post_id}/comments/{comment_id}?profile_id={profile_id}`**

Deletes a comment. Only the comment author can delete their own comment.

### Response — `204 No Content`

No response body.

### Errors

| Status | Reason |
|--------|--------|
| `404` | Comment not found |
| `403` | `profile_id` does not own this comment |

---

## 14. Share Post

**`POST /posts/{post_id}/share?profile_id={profile_id}`**

Records a share event (increments `share_count`). No request body needed. Unlike likes, shares are not toggled — each call adds one more share.

### Response — `200 OK`

```json
{
  "success": true,
  "message": "Share recorded",
  "data": {
    "share_count": 5
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `share_count` | int | Updated total share count on the post |

### Errors

| Status | Reason |
|--------|--------|
| `404` | Post not found |

---

## 15. Save / Unsave Post

**`POST /posts/{post_id}/save?profile_id={profile_id}`**

Toggles the save state. First call = save, second call = unsave. No request body needed.

### Response — `200 OK`

**After saving:**
```json
{
  "success": true,
  "message": "Save toggled",
  "data": {
    "saved": true
  }
}
```

**After unsaving (calling again):**
```json
{
  "success": true,
  "message": "Save toggled",
  "data": {
    "saved": false
  }
}
```

### Errors

| Status | Reason |
|--------|--------|
| `404` | Post not found |

---

## 16. Error Reference

All errors follow this shape:

```json
{
  "detail": "Post 99 not found"
}
```

| HTTP Status | Meaning | When it happens |
|-------------|---------|-----------------|
| `201` | Created | Post or comment created successfully |
| `204` | No Content | Delete succeeded (no body returned) |
| `400` | Bad Request | Malformed request |
| `403` | Forbidden | You do not own the resource you are trying to modify/delete |
| `404` | Not Found | Post or comment does not exist |
| `422` | Unprocessable Entity | Validation failed — check field rules below |

### Common 422 Causes

| Scenario | Error message |
|----------|---------------|
| Empty caption | `"Caption cannot be empty"` |
| Invalid price_type | `"price_type must be one of: fixed, negotiable"` |
| Category 4, missing deal fields | `"Deal/Requirement posts require: grain_type_size, commodity_quantity, price_type"` |
| Category 5, missing description | `"other_description is required when category is 'Other'"` |
| Empty comment content | `"Comment content cannot be empty"` |

---

## Quick Reference — All Endpoints

| Method | Endpoint | Auth (profile_id) | Description |
|--------|----------|-------------------|-------------|
| `POST` | `/posts/upload-image` | Query param | Get signed upload URL for post image |
| `POST` | `/posts/` | Query param | Create a post |
| `GET` | `/posts/` | Query param | Get feed (all posts) |
| `GET` | `/posts/mine` | Query param | Get my posts |
| `GET` | `/posts/following` | Query param | Get following feed (last 7 days) |
| `GET` | `/posts/saved` | Query param | Get saved posts |
| `GET` | `/posts/{post_id}` | Query param | Get single post + record view |
| `PATCH` | `/posts/{post_id}` | Query param | Update post (owner only) |
| `DELETE` | `/posts/{post_id}` | Query param | Delete post (owner only) |
| `POST` | `/posts/{post_id}/like` | Query param | Toggle like |
| `GET` | `/posts/{post_id}/comments` | Query param | Get comments |
| `POST` | `/posts/{post_id}/comments` | Query param | Add comment |
| `DELETE` | `/posts/{post_id}/comments/{comment_id}` | Query param | Delete comment (owner only) |
| `POST` | `/posts/{post_id}/share` | Query param | Record share |
| `POST` | `/posts/{post_id}/save` | Query param | Toggle save |

---

## Testing Checklist

Use this to verify all endpoints are working correctly.

### Setup
- [ ] Server running: `uvicorn main:app --reload`
- [ ] DB migrated: `alembic upgrade head`
- [ ] At least one profile exists (note its `profile_id`)

### Post CRUD
- [ ] **Create** a Market Update post (category 1) — expect `201`, get `post_id`
- [ ] **Create** a Deal post (category 4) with `grain_type_size`, `commodity_quantity`, `price_type` — expect `201`
- [ ] **Create** an Other post (category 5) with `other_description` — expect `201`
- [ ] **Try creating** a Deal post without `price_type` — expect `422`
- [ ] **Try creating** with empty caption — expect `422`
- [ ] **Get feed** — expect `200`, array contains your posts
- [ ] **Get single post** — expect `200`, `view_count` = 1
- [ ] **Get single post again** — expect `200`, `view_count` still = 1 (no double count)
- [ ] **Get my posts** — expect `200`, only your posts
- [ ] **Update** caption — expect `200`, updated caption in response
- [ ] **Try updating** someone else's post — expect `403`
- [ ] **Delete** post — expect `204`
- [ ] **Get deleted post** — expect `404`

### Interactions
- [ ] **Like** a post — expect `200`, `liked: true`, `like_count` incremented
- [ ] **Like again** (unlike) — expect `200`, `liked: false`, `like_count` decremented
- [ ] **Add comment** — expect `201`, get `comment_id`
- [ ] **Add comment** to post with `allow_comments: false` — expect `403`
- [ ] **Get comments** — expect `200`, your comment is in the list
- [ ] **Delete comment** — expect `204`
- [ ] **Delete** someone else's comment — expect `403`
- [ ] **Share** a post — expect `200`, `share_count` incremented
- [ ] **Share again** — expect `200`, `share_count` incremented again (shares are not toggled)
- [ ] **Save** a post — expect `200`, `saved: true`
- [ ] **Get saved posts** — expect `200`, post appears in list
- [ ] **Unsave** (call save again) — expect `200`, `saved: false`
- [ ] **Get saved posts** — expect `200`, post no longer in list

### Runner Scripts

```bash
# Interactive post module tester (needs an existing profile)
python scripts/test_posts.py --profile-id 1

# Full end-to-end flow (onboarding + profile + posts)
python scripts/e2e_flow.py
```
