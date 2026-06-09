# Comments — Frontend Contract

## What Changed

### Breaking API Changes

- **`GET /{post_id}/comments` response shape changed.** Was a plain `CommentCard[]` array. Now a wrapper object:
  ```json
  { "comments": [...], "next_cursor": 55 }
  ```
  Any code doing `response.map(...)` must change to `response.comments.map(...)`.

- **`?offset` removed, `?cursor` added.** Sending `?offset=N` is silently ignored. Pass `next_cursor` from the previous page instead. Omit on first load.

- **`profile_id` field renamed to `commenter_profile_id`.**

- **`created_at` removed from the response.** Use `time_elapsed` (string) instead.

### New Fields on Every CommentCard

- `commenter_name`, `commenter_role`, `commenter_avatar_url`, `commenter_company`
- `commenter_user_id` — UUID string, use for navigating to the commenter's profile
- `is_user_verified`, `is_business_verified`
- `time_elapsed` — e.g. `"just now"`, `"5 minutes ago"`, `"2 days ago"`

---

## Endpoints

### 1. Fetch Comments

```
GET /posts/{post_id}/comments
Authorization: Bearer <token>
```

**Query Parameters**

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `limit` | integer | No | 20 | Max comments per page |
| `cursor` | integer | No | null | Last `comment_id` from the previous page. Omit on first load. |

**Response — direct object, no `data` wrapper**

```json
{
  "comments": [ CommentCard, ... ],
  "next_cursor": 55
}
```

| Field | Type | Description |
|-------|------|-------------|
| `comments` | `CommentCard[]` | Ordered oldest → newest |
| `next_cursor` | `integer \| null` | Pass as `?cursor=` on next request. `null` = no more comments. |

---

### 2. Add Comment

```
POST /posts/{post_id}/comments
Authorization: Bearer <token>
Content-Type: application/json
```

**Request Body**

```json
{ "content": "Looking for 200 MT minimum, are you flexible?" }
```

**Response `201` — wrapped in `ok()`**

```json
{
  "success": true,
  "message": "Comment added successfully",
  "data": CommentCard
}
```

The `data` field contains the newly created `CommentCard`. Append it directly to the bottom of the local list — do not re-fetch.

**Side effects on success:**
- `comment_count` on the post is incremented server-side — update it locally by `+1`.

**Errors**

| Status | Reason |
|--------|--------|
| `403` | Comments are disabled on this post (`allow_comments: false` on the post) |
| `404` | Post not found |

---

### 3. Delete Comment *(backend ready, not surfaced in UI yet)*

```
DELETE /posts/{post_id}/comments/{comment_id}
Authorization: Bearer <token>
```

**Response `204`** — no body.

**Errors**

| Status | Reason |
|--------|--------|
| `403` | You can only delete your own comment |
| `404` | Comment not found |

When this is enabled in UI: only the commenter can delete their own comment. After a successful `204`, remove the card from the local list and decrement `comment_count` by `1`.

---

## CommentCard Schema

```json
{
  "id": 55,
  "post_id": 412,
  "content": "Looking for 200 MT minimum, are you flexible?",
  "commenter_profile_id": 7,
  "commenter_user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "commenter_name": "Harpreet Singh",
  "commenter_role": "Trader",
  "commenter_company": "Singh Agro Exports",
  "commenter_avatar_url": "https://...",
  "is_user_verified": true,
  "is_business_verified": false,
  "time_elapsed": "3 minutes ago"
}
```

### Field Reference

| Field | Type | Notes |
|-------|------|-------|
| `id` | `integer` | Comment ID — also used as the pagination cursor |
| `post_id` | `integer` | Parent post ID |
| `content` | `string` | Comment text |
| `commenter_profile_id` | `integer` | Navigate to profile: `/profile/{commenter_profile_id}` |
| `commenter_user_id` | `string (UUID)` | Auth user ID of commenter — use if the profile screen requires UUID instead of profile ID |
| `commenter_name` | `string` | Display name |
| `commenter_role` | `string` | `"Trader"` \| `"Broker"` \| `"Exporter"` |
| `commenter_company` | `string \| null` | Business name — show as sub-label under commenter name |
| `commenter_avatar_url` | `string \| null` | Avatar image URL |
| `is_user_verified` | `boolean` | Show user-verified badge |
| `is_business_verified` | `boolean` | Show business-verified badge |
| `time_elapsed` | `string` | Human-readable comment age |

> `created_at` is **not** in the response. `time_elapsed` is the only time field sent.

---

## Pagination Flow

```
Open post → GET /posts/{id}/comments          (no cursor)
  ↓
Render first page (oldest comments first)
Store next_cursor
  ↓
User scrolls to bottom of comment list
  → GET /posts/{id}/comments?cursor={next_cursor}
  ↓
Append new comments to the bottom
Update next_cursor
  ↓
next_cursor == null → no more comments, stop fetching
```

Comments are ordered **oldest first** — new comments always appear at the bottom.

---

## Posting a Comment — UI Flow

```
User types and submits
  ↓
POST /posts/{id}/comments  { "content": "..." }
  ↓
201 success:
  → Extract CommentCard from response.data
  → Append to bottom of local comment list
  → Increment local comment_count on the post card by 1
  → Clear input field, dismiss keyboard
  ↓
403 — comments disabled:
  → Show: "Comments are disabled on this post"
  → (Also hide the comment input box if this state is known upfront
     via allow_comments: false on the FeedPostCard)
```

---

## Profile Navigation

Tap commenter name or avatar:
```
→ navigate to /profile/{commenter_profile_id}
```

`commenter_user_id` (UUID) is available if any screen requires the auth UUID rather than the integer profile ID.

---

## Verified Badges

| State | Display |
|-------|---------|
| `is_user_verified: true` | User-verified badge (e.g. blue tick) |
| `is_business_verified: true` | Business-verified badge (e.g. building icon) |
| Both true | Show both badges |
| Both false | No badge |

---

## Disabling Comments Upfront

`FeedPostCard.allow_comments` tells you whether commenting is open before the user tries to submit. Use it to:
- Hide or disable the comment input box entirely
- Show a "Comments disabled" placeholder instead of the input
