# Post Lists — Frontend Contract

Covers three post-list surfaces:
1. **My Posts** — the logged-in user's own posts (`GET /posts/mine`)
2. **Saved Posts** — posts the logged-in user has bookmarked (`GET /posts/saved`)
3. **Another User's Posts** — posts embedded in a public profile response (`GET /profile/{id}` or `GET /profile/by-user/{uuid}`)

All three use cursor-based pagination. No `offset` parameter exists on any of these endpoints.

---

## 1. My Posts

```
GET /posts/mine
Authorization: Bearer <token>
```

**Query Parameters**

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `limit` | integer | No | 20 | Posts per page |
| `cursor` | integer | No | null | Last `post.id` from the previous page. Omit on first load. |

**Response — direct object, no `data` wrapper**

```json
{
  "posts": [ MyPostCard, ... ],
  "next_cursor": 88
}
```

`next_cursor` is `null` when there are no more posts.

### Pagination flow

```
GET /posts/mine               (no cursor)
  → render page 1, store next_cursor

User scrolls to bottom
  → GET /posts/mine?cursor={next_cursor}
  → append to list, update next_cursor

next_cursor == null → no more posts
```

---

## 2. Saved Posts

```
GET /posts/saved
Authorization: Bearer <token>
```

**Query Parameters**

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `limit` | integer | No | 20 | Posts per page |
| `cursor` | integer | No | null | Last save record ID from the previous page. Omit on first load. |

**Response — direct object, no `data` wrapper**

```json
{
  "posts": [ FeedPostCard, ... ],
  "next_cursor": 341
}
```

The cursor here is the internal `PostSave.id` (not the post ID) — always treat it as an opaque integer and pass it back verbatim.

---

## 3. Another User's Posts (embedded in profile)

Posts are not a separate endpoint — they come back inside the profile response.

```
GET /profile/{profile_id}
GET /profile/by-user/{user_uuid}
Authorization: Bearer <token>
```

**Query Parameters**

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `posts_cursor` | integer | No | null | Last `post.id` from the previous page. Omit on first load. |

**Response — wrapped in `ok()`, frontend reads `response.data`**

```json
{
  "success": true,
  "message": "Profile fetched successfully",
  "data": {
    "id": 42,
    "name": "Harpreet Singh",
    "role_id": 1,
    ...all profile fields...,
    "posts": [ FeedPostCard, ... ],
    "posts_next_cursor": 112
  }
}
```

`posts_next_cursor` is `null` when there are no more posts.

### Pagination flow

```
GET /profile/42                        (initial load — no cursor)
  → render full profile + first page of posts
  → store posts_next_cursor from response.data.posts_next_cursor

User scrolls to bottom of post grid
  → GET /profile/42?posts_cursor={posts_next_cursor}
  → append new posts
  → update posts_next_cursor

posts_next_cursor == null → no more posts
```

The full profile data is returned on every call regardless of cursor. The frontend can ignore the profile fields on paginated requests and only use the `posts` + `posts_next_cursor` fields.

---

## Card Schemas

### FeedPostCard
Used by: Saved Posts, Another User's Profile Posts

```json
{
  "id": 412,
  "profile_id": 7,
  "category_id": 4,
  "commodity_id": 1,
  "title": "100 MT Rice Available — FAQ Grade",
  "caption": "...",
  "image_urls": ["https://..."],
  "source_url": null,
  "allow_comments": true,
  "deal_details": {
    "grain_type": "Parboiled",
    "grain_size": "Long",
    "commodity_quantity": 100.0,
    "quantity_unit": "MT",
    "commodity_price": 2800.0,
    "price_type": "negotiable",
    "is_closed": false
  },
  "location_name": "Karnal Mandi",
  "location_city": "Karnal",
  "location_state": "Haryana",
  "like_count": 14,
  "comment_count": 3,
  "is_liked": false,
  "is_saved": true,
  "time_elapsed": "2 hours ago",
  "author_name": "Harpreet Singh",
  "author_role": "Trader",
  "author_user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "author_company": "Singh Agro Exports",
  "author_avatar_url": "https://...",
  "is_following": true,
  "is_user_verified": true,
  "is_business_verified": false
}
```

### MyPostCard
Used by: My Posts — everything in `FeedPostCard` plus owner-only fields.

```json
{
  ...all FeedPostCard fields...,

  "created_at": "2026-06-08T10:30:00Z",
  "is_public": true,
  "target_roles": null,
  "view_count": 142,
  "share_count": 5,
  "save_count": 8
}
```

#### Extra fields (owner-only)

| Field | Type | Description |
|-------|------|-------------|
| `created_at` | ISO datetime | Full timestamp — for display or sorting |
| `is_public` | boolean | `true` = visible to all; `false` = followers only |
| `target_roles` | `int[] \| null` | Targeted role IDs (1=Trader, 2=Broker, 3=Exporter); `null` = all roles |
| `view_count` | integer | Total post views |
| `share_count` | integer | Total shares |
| `save_count` | integer | Total saves by other users |

---

## Response Wrapper Summary

| Endpoint | Wrapper | Read from |
|----------|---------|-----------|
| `GET /posts/mine` | None | `response.posts`, `response.next_cursor` |
| `GET /posts/saved` | None | `response.posts`, `response.next_cursor` |
| `GET /profile/{id}` | `ok()` | `response.data.posts`, `response.data.posts_next_cursor` |
| `GET /profile/by-user/{uuid}` | `ok()` | `response.data.posts`, `response.data.posts_next_cursor` |

---

## FeedPostCard Field Reference

| Field | Type | Notes |
|-------|------|-------|
| `id` | integer | Post ID |
| `profile_id` | integer | Author's profile ID |
| `category_id` | integer | 1=Market Update, 2=Knowledge, 3=Discussion, 4=Deal/Req |
| `commodity_id` | integer | 1=Rice, 2=Cotton, 3=Sugar |
| `title` | string | Post title |
| `caption` | string | Post body |
| `image_urls` | `string[] \| null` | Up to 5 image URLs |
| `source_url` | `string \| null` | External link |
| `allow_comments` | boolean | Hide/disable comment input when `false` |
| `deal_details` | `DealDetails \| null` | Only present for category_id=4 |
| `location_name` | `string \| null` | Author-provided label e.g. "Karnal Mandi" |
| `location_city` | `string \| null` | From author's business profile |
| `location_state` | `string \| null` | From author's business profile |
| `like_count` | integer | |
| `comment_count` | integer | |
| `is_liked` | boolean | Has the viewing user liked this post |
| `is_saved` | boolean | Has the viewing user saved this post |
| `time_elapsed` | string | e.g. `"just now"`, `"3 hours ago"`, `"2 days ago"` |
| `author_name` | string | |
| `author_role` | string | `"Trader"` \| `"Broker"` \| `"Exporter"` |
| `author_user_id` | string (UUID) | Use for Follow button or profile navigation |
| `author_company` | `string \| null` | Business name |
| `author_avatar_url` | `string \| null` | |
| `is_following` | boolean | Is the viewer following this author |
| `is_user_verified` | boolean | Show user-verified badge |
| `is_business_verified` | boolean | Show business-verified badge |

> `created_at` is **not** present on `FeedPostCard`. Use `time_elapsed` for display. It is present on `MyPostCard`.
