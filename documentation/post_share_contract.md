# Post Share — Frontend Contract

## Flow Overview

```
User taps "Share" on a post
        │
        ▼
1. GET /posts/{post_id}/share
        │  → renders the share-sheet picker (DMs + groups)
        │
User selects recipients + optionally types a caption
        │
        ▼
2. POST /posts/{post_id}/send
        │  → delivers post as chat message to each recipient
        │  → WebSocket event fires to each recipient
        │
        ▼
   Show "Sent to N" confirmation

─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
Separate path — external share (WhatsApp, copy link, etc.):

3. POST /posts/{post_id}/record-share
        │  → telemetry only, no chat delivery
```

---

## 1. Get Share Sheet

**`GET /posts/{post_id}/share`**

Auth: Bearer token required

Path param: `post_id` — integer ID of the post being shared

**No `ok()` wrapper — read directly from `response`.**

**Response `200`:**
```json
{
  "dms": [
    {
      "conversation_id": "uuid",
      "user": {
        "user_id": "uuid",
        "profile_id": 12,
        "name": "Ravi Mehta",
        "avatar_url": "https://...",
        "role": "Trader",
        "is_user_verified": true,
        "is_business_verified": false,
        "is_online": true
      }
    }
  ],
  "groups": [
    {
      "group_id": "uuid",
      "name": "Cotton Traders Mumbai",
      "avatar_url": "https://...",
      "member_count": 14
    }
  ]
}
```

**Notes:**
- Only returns DM conversations with status `ACTIVE` (accepted message requests)
- Only returns groups where the user is a member and not frozen
- `post_id` in the path is not used to filter recipients — same list regardless of which post is being shared

---

## 2. Send (In-App Delivery)

**`POST /posts/{post_id}/send`**

Auth: Bearer token required

Path param: `post_id` — integer ID of the post being shared

**Request body:**
```json
{
  "dm_conversation_ids": ["uuid", "uuid"],
  "group_ids": ["uuid"],
  "caption": "Check this out"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `dm_conversation_ids` | `UUID[]` | at least one of the two | conversation IDs from share-sheet |
| `group_ids` | `UUID[]` | at least one of the two | group IDs from share-sheet |
| `caption` | `string \| null` | no | max 4000 chars |

Validation: at least one of `dm_conversation_ids` or `group_ids` must be non-empty, else `422`.

**No `ok()` wrapper — read directly from `response`.**

**Response `200`:**
```json
{
  "share_count": 47,
  "delivered_to": 3
}
```

| Field | Meaning |
|---|---|
| `share_count` | Total lifetime share count on this post (all users) |
| `delivered_to` | Number of DMs + groups this send actually reached |

**Notes:**
- `delivered_to` may be less than the total recipients passed — permission checks run per-recipient and silently skip failures
- `share_count` is incremented **once** per call regardless of `delivered_to`

**Error responses:**
```json
{ "detail": "Post not found" }   // 404 — post_id doesn't exist
{ "detail": [...] }              // 422 — no recipients, caption too long, etc.
```

---

## 3. External / Record Share (Telemetry Only)

**`POST /posts/{post_id}/record-share`**

Auth: Bearer token required

No request body. No query params.

**Wrapped in `ok()` — read from `response.data`.**

**Response `200`:**
```json
{
  "success": true,
  "message": "Share recorded",
  "data": {
    "share_count": 48
  }
}
```

Use this when the user shares externally (copies link, shares to WhatsApp). It increments `share_count` — no chat message is created.

---

## WebSocket Events (Recipient Side)

When `POST /send` delivers successfully, each recipient gets a push over their existing WebSocket connection.

**DM recipient** — event: `new_message`
```json
{
  "id": "uuid",
  "context_id": "conversation_uuid",
  "context_type": "dm",
  "sender": {
    "user_id": "uuid",
    "name": "Aadya Pande",
    "avatar_url": "https://..."
  },
  "message_type": "post",
  "body": "Check this out",
  "post": {
    "post_id": 412,
    "title": "100 MT Rice Available — FAQ Grade",
    "image_url": "https://...",
    "author_name": "Harpreet Singh",
    "category_id": 4,
    "commodity_id": 1
  },
  "sent_at": "2026-06-25T10:30:00Z"
}
```

**Group recipient** — event: `new_group_message`, same shape with `context_type: "group"`.

---

## Endpoint Summary

| Endpoint | Auth | `ok()` wrapper | Purpose | Creates chat msg |
|---|---|---|---|---|
| `GET /posts/{id}/share` | ✅ | No — read `response` directly | Fetch share-sheet picker | No |
| `POST /posts/{id}/send` | ✅ | No — read `response` directly | In-app delivery to DMs/groups | **Yes** |
| `POST /posts/{id}/record-share` | ✅ | Yes — read `response.data` | External share telemetry | No |

---

## Common Mistakes

| Mistake | Correct |
|---|---|
| `POST /posts/{id}/share` | This is **GET**, not POST — returns 405 |
| Reading `response.data` on `/send` | No wrapper — read `response.share_count` directly |
| Reading `response.share_count` on `/record-share` | Has wrapper — read `response.data.share_count` |
