# Connections Module — Developer Guide

A complete reference for the follow system, message requests, and user search.

**Base URL:** `https://vanijyaa-backend.onrender.com`

**Interactive docs (Swagger):** `https://vanijyaa-backend.onrender.com/docs`

---

## Table of Contents

1. [Module Overview](#1-module-overview)
2. [How User Identity Works](#2-how-user-identity-works)
3. [Database Schema](#3-database-schema)
4. [File Structure](#4-file-structure)
5. [API Quick Reference](#5-api-quick-reference)
6. [Follow APIs](#6-follow-apis)
7. [Message Request APIs](#7-message-request-apis)
8. [Search APIs](#8-search-apis)
9. [Shared User Object](#9-shared-user-object)
10. [Error Reference](#10-error-reference)

---

## 1. Module Overview

The connections module handles three things:

- **Follow** — one-directional, no approval needed. User A follows User B instantly.
- **Message requests** — bidirectional, requires acceptance. User A sends a request, User B must accept or decline.
- **Search** — text search across all profiles with optional filters.

---

## 2. How User Identity Works

All mutating endpoints require `Authorization: Bearer <token>`. The acting user's identity is derived exclusively from the JWT — **never** from a path or query parameter.

```
POST /connections/follow/{target_id}
Authorization: Bearer <access_token>
```

`{target_id}` is the user you want to follow. Your own identity (`me`) comes from the token automatically.

Public read-only endpoints (`GET /{user_id}/followers`, `GET /{user_id}/following`, `GET /search/suggestions`) do not require a token.

> **Migration note (2026-05-12):** The old `/{user_id}/follow/{target_id}` pattern (where the acting user was in the path) has been removed. All callers must send a Bearer token instead.

---

## 3. Database Schema

### `user_connections` — follow relationships

| Column | Type | Notes |
|---|---|---|
| `follower_id` | UUID FK → users.id | The user who pressed Follow |
| `following_id` | UUID FK → users.id | The user being followed |
| `followed_at` | TIMESTAMPTZ | Timestamp of the follow action |

Composite primary key: `(follower_id, following_id)`. One row = one follow. No status column — row existing means following.

### `message_requests` — message request lifecycle

| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL PK | Auto-increment |
| `sender_id` | UUID FK → users.id | User who sent the request |
| `receiver_id` | UUID FK → users.id | User who needs to accept or decline |
| `status` | VARCHAR | `pending` → `accepted` or `declined` |
| `sent_at` | TIMESTAMPTZ | When request was sent |
| `acted_at` | TIMESTAMPTZ | When accepted/declined — `NULL` while pending |

UNIQUE constraint on `(sender_id, receiver_id)`.

---

## 4. File Structure

```
app/modules/connections/
  models.py    ← SQLAlchemy ORM (UserConnection, MessageRequest)
  schemas.py   ← Pydantic DTOs
  service.py   ← All business logic (follow, message requests, search, recommendations)
  router.py    ← FastAPI route handlers
  encoding/
    vector.py  ← IS/WANT vector builders for recommendations
```

---

## 5. API Quick Reference

Base prefix: `/connections`

`{user_id}` = acting user's UUID. `{target_id}` = the other party's UUID.

No token required on any endpoint.

| Method | Endpoint | What it does |
|---|---|---|
| `POST` | `/connections/{user_id}/follow/{target_id}` | Follow a user |
| `DELETE` | `/connections/{user_id}/follow/{target_id}` | Unfollow a user |
| `GET` | `/connections/{user_id}/followers` | List everyone who follows user_id |
| `GET` | `/connections/{user_id}/following` | List everyone user_id follows |
| `GET` | `/connections/{user_id}/follow/status/{target_id}` | Check if user_id is following target_id |
| `POST` | `/connections/{user_id}/message-request/{target_id}` | Send a message request |
| `DELETE` | `/connections/{user_id}/message-request/{target_id}` | Withdraw a pending request |
| `PATCH` | `/connections/{user_id}/message-request/{request_id}/accept` | Accept a request |
| `PATCH` | `/connections/{user_id}/message-request/{request_id}/decline` | Decline a request |
| `GET` | `/connections/{user_id}/message-requests/received` | Pending inbox |
| `GET` | `/connections/{user_id}/message-requests/sent` | Requests sent |
| `GET` | `/connections/{user_id}/search` | Search profiles — filters: `q`, `role`, `commodity`, `city`, `verified_only`; pagination: `page`, `limit` |
| `GET` | `/connections/search/suggestions?q=...` | Name/business suggestions |

---

## 6. Follow APIs

### `POST /connections/{user_id}/follow/{target_id}`

Follow a user. Instant — no approval required.

| URL Param | Type | Description |
|---|---|---|
| `user_id` | UUID | The acting user (who presses Follow) |
| `target_id` | UUID | The user to follow |

No request body. No token required.

**Example:**
```
POST /connections/c37a3257-dc3f-43be-9fb0-33cf918b11ff/follow/a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

**Success `200`:**
```json
{ "status": "following", "following_id": "a1b2c3d4-..." }
```

**Error `409`** — already following:
```json
{ "detail": "Already following this user." }
```

---

### `DELETE /connections/{user_id}/follow/{target_id}`

Unfollow a user.

**Example:**
```
DELETE /connections/c37a3257-dc3f-43be-9fb0-33cf918b11ff/follow/a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

**Success `200`:**
```json
{ "status": "unfollowed", "following_id": "a1b2c3d4-..." }
```

**Error `404`** — not currently following:
```json
{ "detail": "You are not following this user." }
```

---

### `GET /connections/{user_id}/followers`

Get everyone who follows this user.

**Example:**
```
GET /connections/c37a3257-dc3f-43be-9fb0-33cf918b11ff/followers
```

**Success `200`:**
```json
{
    "user_id": "c37a3257-...",
    "total": 1,
    "followers": [
        {
            "user_id": "a1b2c3d4-...",
            "name": "Ravi Traders",
            "business_name": "Ravi Agro",
            "role": "trader",
            "commodity": ["rice", "cotton"],
            "is_verified": false,
            "qty_range": "100–500mt",
            "followed_at": "2026-04-15T08:19:31.248438+00:00"
        }
    ]
}
```

Results ordered by `followed_at DESC`.

---

### `GET /connections/{user_id}/following`

Get everyone this user follows. Same response shape as followers, with `"following"` array key.

---

### `GET /connections/{user_id}/follow/status/{target_id}`

Check whether `user_id` is currently following `target_id`. Use this to drive the Follow / Unfollow button state.

**Example:**
```
GET /connections/c37a3257-dc3f-43be-9fb0-33cf918b11ff/follow/status/a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

**Success `200`:**
```json
{ "me": "c37a3257-...", "target": "a1b2c3d4-...", "following": true }
```

`following` is always `true` or `false` — never a 404.

---

## 7. Message Request APIs

### `POST /connections/{user_id}/message-request/{target_id}`

Send a message request. Status is `pending` on creation.

No request body. No token required.

**Example:**
```
POST /connections/c37a3257-dc3f-43be-9fb0-33cf918b11ff/message-request/a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

**Success `200`:**
```json
{ "status": "sent", "id": 4, "sent_at": "2026-04-15T10:00:00.000000+00:00" }
```

**Error `409`** — request already exists:
```json
{ "detail": "Message request already sent." }
```

---

### `DELETE /connections/{user_id}/message-request/{target_id}`

Withdraw a pending request. Only works while status is `pending`.

**Example:**
```
DELETE /connections/c37a3257-dc3f-43be-9fb0-33cf918b11ff/message-request/a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

**Success `200`:**
```json
{ "status": "withdrawn", "receiver_id": "a1b2c3d4-..." }
```

---

### `PATCH /connections/{user_id}/message-request/{request_id}/accept`

Accept a message request. `user_id` must be the receiver. Use `request_id` from the received inbox.

**Example:**
```
PATCH /connections/a1b2c3d4-e5f6-7890-abcd-ef1234567890/message-request/4/accept
```

**Success `200`:**
```json
{ "id": 4, "status": "accepted" }
```

**Error `404`** — not found, already acted on, or wrong receiver:
```json
{ "detail": "Request not found, already acted on, or you are not the receiver." }
```

---

### `PATCH /connections/{user_id}/message-request/{request_id}/decline`

Same rules as accept.

**Success `200`:**
```json
{ "id": 4, "status": "declined" }
```

---

### `GET /connections/{user_id}/message-requests/received`

All pending requests waiting for `user_id` to accept or decline. Only returns `pending` status.

**Example:**
```
GET /connections/a1b2c3d4-e5f6-7890-abcd-ef1234567890/message-requests/received
```

**Success `200`:**
```json
{
    "user_id": "a1b2c3d4-...",
    "total": 1,
    "requests": [
        {
            "request_id": 4,
            "from": {
                "user_id": "c37a3257-...",
                "name": "Ravi Traders",
                "role": "trader",
                "commodity": ["rice", "cotton"],
                "qty_range": "100–500mt"
            },
            "sent_at": "2026-04-15T10:00:00.000000+00:00"
        }
    ]
}
```

Use `request_id` when calling accept or decline.

---

### `GET /connections/{user_id}/message-requests/sent`

All requests sent by `user_id`, across all statuses.

**Success `200`:**
```json
{
    "user_id": "c37a3257-...",
    "total": 1,
    "requests": [
        {
            "request_id": 4,
            "to": {
                "user_id": "a1b2c3d4-...",
                "name": "Anita Shah",
                "role": "broker",
                "commodity": ["rice"],
                "qty_range": "200–800mt"
            },
            "status": "pending",
            "sent_at": "2026-04-15T10:00:00.000000+00:00",
            "acted_at": null
        }
    ]
}
```

`acted_at` is `null` while pending. Filled once the receiver accepts or declines.

---

## 8. Search APIs

### `GET /connections/{user_id}/search`

Search profiles on the platform. `user_id` is always excluded from results. All filter params optional.

| Query Param | Required | Type | Default | Description |
|---|---|---|---|---|
| `q` | No | string | — | Partial match on name or business name |
| `role` | No | string | — | Exact: `trader`, `broker`, `exporter` |
| `commodity` | No | string | — | Partial match on commodity name |
| `city` | No | string | — | Partial match on city name |
| `verified_only` | No | bool | `false` | When `true`, return only verified users |
| `page` | No | int | `1` | Page number (1-based) |
| `limit` | No | int | `20` | Results per page (max 100) |

**Examples:**
```
GET /connections/c37a3257-.../search?q=ravi
GET /connections/c37a3257-.../search?role=exporter&commodity=rice
GET /connections/c37a3257-.../search?city=mumbai&verified_only=true
GET /connections/c37a3257-.../search?page=2&limit=10
```

**Success `200`:**
```json
{
    "total": 2,
    "page": 1,
    "limit": 20,
    "results": [
        {
            "user_id": "a1b2c3d4-...",
            "name": "Anita Shah",
            "business_name": "Shah Exports",
            "role": "exporter",
            "commodity": ["sugar"],
            "city": "Mumbai",
            "is_verified": true,
            "qty_range": "1000–5000mt"
        }
    ]
}
```

---

### `GET /connections/search/suggestions?q=...`

Name/business name suggestions. Returns top 8 matches that contain the query string.

| Query Param | Required | Description |
|---|---|---|
| `q` | Yes | Search term — minimum 2 characters |

**Example:**
```
GET /connections/search/suggestions?q=rav
```

**Success `200`:**
```json
{
    "q": "rav",
    "total": 3,
    "suggestions": [
        {
            "user_id": "c37a3257-...",
            "name": "Ravi Traders",
            "business_name": "Ravi Agro Pvt Ltd",
            "role": "trader",
            "commodity": ["rice", "cotton"],
            "is_verified": false
        }
    ]
}
```

---

## 9. Shared User Object

Every profile object across all endpoints has this shape:

```json
{
    "user_id": "uuid",
    "name": "Ravi Traders",
    "business_name": "Ravi Agro Pvt Ltd",
    "role": "trader",
    "commodity": ["rice", "cotton"],
    "is_verified": false,
    "qty_range": "100–500mt"
}
```

Some endpoints add extra fields:

| Endpoint | Extra fields |
|---|---|
| `GET /followers` | `followed_at` |
| `GET /following` | `followed_at` |
| `GET /message-requests/received` | `sent_at` |
| `GET /message-requests/sent` | `status`, `sent_at`, `acted_at` |

---

## 10. Error Reference

| Status | When it happens |
|---|---|
| `404` | Not following, no pending request found, request already acted on, or wrong receiver |
| `409` | Already following, message request already exists |
| `422` | Missing required field or wrong data type |

All errors follow FastAPI's shape:
```json
{ "detail": "Human-readable message." }
```
