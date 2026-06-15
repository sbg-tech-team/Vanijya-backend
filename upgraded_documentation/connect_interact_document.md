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
9. [Recommendation APIs](#9-recommendation-apis)
10. [Shared User Object](#10-shared-user-object)
11. [Error Reference](#11-error-reference)

---

## 1. Module Overview

The connections module handles four things:

- **Follow** — one-directional, no approval needed. User A follows User B instantly.
- **Message requests** — bidirectional, requires acceptance. User A sends a request (optionally with an opening line), User B must accept or decline. **On accept, a DM conversation is opened in `active` state, the opening line is seeded as its first message, and the original sender receives a `message_request_accepted` Socket.IO push** so both sides can start chatting immediately. This is the canonical "request to chat" gate that feeds the chat module.
- **Search** — text search across all profiles with optional filters.
- **Recommendations** — vector-based "people you may know" matching using pgvector HNSW cosine ANN search. Lives under `/recommendations/`.

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
| `first_message` | TEXT (nullable) | Optional opening line attached to the request; seeded as the first DM message on accept |
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

Mutating endpoints require `Authorization: Bearer <access_token>`. The acting user's identity comes from the JWT — never from a path or query parameter. Public read endpoints are marked below.

| Method | Endpoint | Auth | What it does |
|---|---|---|---|
| `POST` | `/connections/follow/{target_id}` | Bearer token | Follow a user — returns **201** |
| `DELETE` | `/connections/follow/{target_id}` | Bearer token | Unfollow a user |
| `GET` | `/connections/follow/status/{target_id}` | Bearer token | Check if I am following target |
| `GET` | `/connections/{user_id}/followers` | **Public** | List everyone who follows user_id |
| `GET` | `/connections/{user_id}/following` | **Public** | List everyone user_id follows |
| `POST` | `/connections/message-request/{target_id}` | Bearer token | Send a message request — returns **201** |
| `DELETE` | `/connections/message-request/{target_id}` | Bearer token | Withdraw a pending request |
| `PATCH` | `/connections/message-request/{request_id}/accept` | Bearer token | Accept a request |
| `PATCH` | `/connections/message-request/{request_id}/decline` | Bearer token | Decline a request |
| `GET` | `/connections/message-requests/received` | Bearer token | Pending inbox |
| `GET` | `/connections/message-requests/sent` | Bearer token | Requests sent |
| `GET` | `/connections/search` | Bearer token | Search profiles — filters: `q`, `role`, `commodity`, `city`, `user_verified_only`, `business_verified_only`; pagination: `page`, `limit` |
| `GET` | `/connections/search/suggestions?q=...` | **Public** | Name/business suggestions |
| `GET` | `/recommendations/` | Bearer token | Paginated vector-matched users — `page`, `limit` (default 20, max 100) |
| `POST` | `/recommendations/search` | **Public** | Ad-hoc vector search with custom payload — no account needed |

---

## 6. Follow APIs

### `POST /connections/follow/{target_id}`

Follow a user. Instant — no approval required.

| URL Param | Type | Description |
|---|---|---|
| `target_id` | UUID | The user to follow |

No request body. Acting user identity comes from `Authorization: Bearer <access_token>`.

**Example:**
```
POST /connections/follow/a1b2c3d4-e5f6-7890-abcd-ef1234567890
Authorization: Bearer <access_token>
```

**Success `201`:**
```json
{
  "success": true,
  "message": "Now following",
  "data": { "status": "following", "following_id": "a1b2c3d4-..." }
}
```

**Error `409`** — already following:
```json
{ "detail": "Already following this user." }
```

---

### `DELETE /connections/follow/{target_id}`

Unfollow a user.

**Example:**
```
DELETE /connections/follow/a1b2c3d4-e5f6-7890-abcd-ef1234567890
Authorization: Bearer <access_token>
```

**Success `200`:**
```json
{
  "success": true,
  "message": "Unfollowed",
  "data": { "status": "unfollowed", "following_id": "a1b2c3d4-..." }
}
```

**Error `404`** — not currently following:
```json
{ "detail": "You are not following this user." }
```

---

### `GET /connections/{user_id}/followers`

Get everyone who follows this user. **Public — no token required.**

**Example:**
```
GET /connections/c37a3257-dc3f-43be-9fb0-33cf918b11ff/followers
```

**Success `200`:**
```json
{
  "success": true,
  "message": "Followers fetched",
  "data": {
    "total": 1,
    "followers": [
      {
        "user_id": "a1b2c3d4-...",
        "name": "Ravi Traders",
        "avatar_url": null,
        "role": "trader",
        "commodity": ["rice", "cotton"],
        "is_user_verified": false,
        "is_business_verified": false,
        "quantity_min": 100,
        "quantity_max": 500,
        "business_name": "Ravi Agro",
        "city": "Mumbai",
        "state": "Maharashtra",
        "followed_at": "2026-04-15T08:19:31.248438+00:00"
      }
    ]
  }
}
```

Results ordered by `followed_at DESC`.

---

### `GET /connections/{user_id}/following`

Get everyone this user follows. **Public — no token required.** Same response shape as followers, with `"following"` array key.

---

### `GET /connections/follow/status/{target_id}`

Check whether the authenticated user is currently following `target_id`. Use this to drive the Follow / Unfollow button state. Requires `Authorization: Bearer <access_token>`.

**Example:**
```
GET /connections/follow/status/a1b2c3d4-e5f6-7890-abcd-ef1234567890
Authorization: Bearer <access_token>
```

**Success `200`:**
```json
{
  "success": true,
  "message": "Follow status fetched",
  "data": { "following": true }
}
```

`following` is always `true` or `false` — never a 404.

---

## 7. Message Request APIs

### `POST /connections/message-request/{target_id}`

Send a message request. Status is `pending` on creation. Acting user identity comes from `Authorization: Bearer <access_token>`.

**Request body (optional):**
```json
{ "first_message": "Hi, interested in your 500 MT Basmati listing?" }
```

| Field | Required | Type | Notes |
|---|---|---|---|
| `first_message` | No | string (≤ 2000 chars) | Opening line shown to the receiver and seeded as the conversation's first message once accepted. Omit (or send an empty body) for a bare connect request. |

> Re-sending a previously **declined** request reopens it as `pending` and overwrites `first_message` with the new value.

**Example:**
```
POST /connections/message-request/a1b2c3d4-e5f6-7890-abcd-ef1234567890
Authorization: Bearer <access_token>
Content-Type: application/json

{ "first_message": "Hi, interested in your 500 MT Basmati listing?" }
```

**Success `201`:**
```json
{
  "success": true,
  "message": "Message request sent",
  "data": { "status": "sent", "id": 4, "sent_at": "2026-04-15T10:00:00.000000+00:00" }
}
```

**Error `409`** — request already exists:
```json
{ "detail": "Message request already sent." }
```

---

### `DELETE /connections/message-request/{target_id}`

Withdraw a pending request. Only works while status is `pending`.

**Example:**
```
DELETE /connections/message-request/a1b2c3d4-e5f6-7890-abcd-ef1234567890
Authorization: Bearer <access_token>
```

**Success `200`:**
```json
{
  "success": true,
  "message": "Request withdrawn",
  "data": { "status": "withdrawn", "receiver_id": "a1b2c3d4-..." }
}
```

---

### `PATCH /connections/message-request/{request_id}/accept`

Accept a message request. The authenticated user must be the receiver. Use `request_id` from the received inbox.

On accept the backend, in one transaction:
1. Marks the request `accepted`.
2. Opens the DM conversation between the two users in **`active`** status (creating it if needed; the request sender is recorded as the conversation `initiator_id`).
3. If the request carried a `first_message`, seeds it as the conversation's first message (sender = the request sender).
4. Pushes a `message_request_accepted` Socket.IO event to the **original sender's** `user:{sender_id}` room.

**Example:**
```
PATCH /connections/message-request/4/accept
Authorization: Bearer <access_token>
```

**Success `200`:**
```json
{
  "success": true,
  "message": "Request accepted",
  "data": {
    "id": 4,
    "status": "accepted",
    "sender_id": "c37a3257-dc3f-43be-9fb0-33cf918b11ff",
    "conversation_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
  }
}
```

| Field | Notes |
|---|---|
| `sender_id` | The user who originally sent the request (and who receives the WS push) |
| `conversation_id` | The now-active DM conversation — open it with the chat APIs (`GET /chat/conversations/{conversation_id}/messages`) |

**WS push:** fires `message_request_accepted` to `user:{sender_id}` with:
```json
{ "request_id": 4, "conversation_id": "3fa85f64-...", "accepted_by": "<receiver-uuid>" }
```
The sender's client should open/refresh the conversation on receipt. (See the chat module's [Socket.IO events](chat_module.md#6-socketio--real-time-connection).)

**Error `404`** — not found, already acted on, or wrong receiver:
```json
{ "detail": "Request not found, already acted on, or you are not the receiver." }
```

---

### `PATCH /connections/message-request/{request_id}/decline`

Same rules as accept.

**Success `200`:**
```json
{
  "success": true,
  "message": "Request declined",
  "data": { "id": 4, "status": "declined" }
}
```

---

### `GET /connections/message-requests/received`

All pending requests waiting for the authenticated user to accept or decline. Only returns `pending` status.

**Example:**
```
GET /connections/message-requests/received
Authorization: Bearer <access_token>
```

**Success `200`:**
```json
{
  "success": true,
  "message": "Received requests fetched",
  "data": {
    "total": 1,
    "requests": [
      {
        "request_id": 4,
        "from": {
          "user_id": "c37a3257-...",
          "name": "Ravi Traders",
          "avatar_url": null,
          "role": "trader",
          "commodity": ["rice", "cotton"],
          "is_user_verified": false,
          "is_business_verified": false,
          "quantity_min": 100,
          "quantity_max": 500,
          "business_name": "Ravi Agro",
          "city": "Mumbai",
          "state": "Maharashtra"
        },
        "first_message": "Hi, interested in your 500 MT Basmati listing?",
        "sent_at": "2026-04-15T10:00:00.000000+00:00"
      }
    ]
  }
}
```

`first_message` is the opening line the sender attached (or `null` for a bare connect request) — show it as a preview so the receiver can decide before accepting. Use `request_id` when calling accept or decline.

---

### `GET /connections/message-requests/sent`

All requests sent by the authenticated user, across all statuses.

**Example:**
```
GET /connections/message-requests/sent
Authorization: Bearer <access_token>
```

**Success `200`:**
```json
{
  "success": true,
  "message": "Sent requests fetched",
  "data": {
    "total": 1,
    "requests": [
      {
        "request_id": 4,
        "to": {
          "user_id": "a1b2c3d4-...",
          "name": "Anita Shah",
          "avatar_url": null,
          "role": "broker",
          "commodity": ["rice"],
          "is_user_verified": false,
          "is_business_verified": false,
          "quantity_min": 200,
          "quantity_max": 800,
          "business_name": "Shah Brokers",
          "city": "Delhi",
          "state": "Delhi"
        },
        "status": "pending",
        "first_message": "Hi, interested in your 500 MT Basmati listing?",
        "sent_at": "2026-04-15T10:00:00.000000+00:00",
        "acted_at": null
      }
    ]
  }
}
```

`acted_at` is `null` while pending. Filled once the receiver accepts or declines.

---

## 8. Search APIs

### `GET /connections/search`

Search profiles on the platform. The authenticated user is always excluded from results. All filter params optional. Requires `Authorization: Bearer <access_token>`.

| Query Param | Required | Type | Default | Description |
|---|---|---|---|---|
| `q` | No | string | — | Free-text query — smart-parsed when used alone (see below), or name/business name match when used alongside explicit filters |
| `role` | No | string | — | Explicit role filter: `trader`, `broker`, `exporter` |
| `commodity` | No | string | — | Explicit commodity filter: `cotton`, `rice`, `sugar` |
| `city` | No | string | — | Partial match on city name |
| `user_verified_only` | No | bool | `false` | When `true`, return only KYC-verified users (`is_user_verified = true`) |
| `business_verified_only` | No | bool | `false` | When `true`, return only KYB-verified users (`is_business_verified = true`) |
| `page` | No | int | `1` | Page number (1-based) |
| `limit` | No | int | `20` | Results per page (max 100) |

---

#### Smart query parsing (single search box)

When `q` is provided **and none of `role`, `commodity`, `city` are explicitly set**, the backend parses intent from the free text automatically:

| What it detects | How |
|---|---|
| Role | Token matches `trader`, `broker`, `exporter` (or plural: `traders`, `brokers`, `exporters`) |
| Commodity | Token matches a known commodity: `cotton`, `rice`, `sugar` |
| City | Looks for `in <word>` or `from <word>` pattern in the query |
| Name | Any remaining tokens become a name / business name ILIKE filter |

**Explicit params always take priority** — if `role=broker` is passed alongside `q`, the role inside `q` is ignored and `role=broker` is used.

**Parsed query examples:**

| `q` value | Resolved as |
|---|---|
| `ravi` | name ILIKE `%ravi%` |
| `cotton` | commodity = cotton |
| `broker` | role = broker |
| `rice exporters` | role = exporter, commodity = rice |
| `ravi broker` | role = broker, name ILIKE `%ravi%` |
| `cotton traders in mumbai` | role = trader, commodity = cotton, city = mumbai |
| `exporters in delhi` | role = exporter, city = delhi |

---

**Single-box examples (smart parsed):**
```
GET /connections/search?q=ravi
GET /connections/search?q=cotton
GET /connections/search?q=broker
GET /connections/search?q=rice exporters
GET /connections/search?q=cotton traders in mumbai
```

**Explicit filter examples:**
```
GET /connections/search?role=exporter&commodity=rice
GET /connections/search?city=mumbai&user_verified_only=true
GET /connections/search?user_verified_only=true&business_verified_only=true
GET /connections/search?page=2&limit=10
```

Both `user_verified_only` and `business_verified_only` can be combined with any search mode.

**Success `200`:**
```json
{
  "success": true,
  "message": "Search results fetched",
  "data": {
    "total": 2,
    "page": 1,
    "limit": 20,
    "results": [
      {
        "user_id": "a1b2c3d4-...",
        "name": "Anita Shah",
        "avatar_url": null,
        "role": "exporter",
        "commodity": ["sugar"],
        "is_user_verified": true,
        "is_business_verified": false,
        "quantity_min": 1000,
        "quantity_max": 5000,
        "business_name": "Shah Exports",
        "city": "Mumbai",
        "state": "Maharashtra",
        "msg_req_status": null,
        "follow_status": false
      }
    ]
  }
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
  "success": true,
  "message": "Suggestions fetched",
  "data": {
    "total": 3,
    "suggestions": [
      {
        "user_id": "c37a3257-...",
        "name": "Ravi Traders",
        "avatar_url": null,
        "role": "trader",
        "commodity": ["rice", "cotton"],
        "is_user_verified": false,
        "is_business_verified": false,
        "quantity_min": 100,
        "quantity_max": 500,
        "business_name": "Ravi Agro Pvt Ltd",
        "city": "Mumbai",
        "state": "Maharashtra"
      }
    ]
  }
}
```

---

## 9. Recommendation APIs

Recommendations live under `/recommendations/` (separate prefix from `/connections/`). They use pgvector HNSW cosine ANN search against stored IS vectors in `user_embeddings`.

---

### `GET /recommendations/`

Returns paginated best-matched users for the authenticated user. Requires `Authorization: Bearer <access_token>`.

How it works:
1. Loads the caller's profile (role, commodities, business location, quantity range).
2. Builds a WANT vector using `build_query_vector()`.
3. Runs HNSW ANN cosine search — excludes the caller and users they already follow.
4. Returns `limit` results for the given `page`, ordered by similarity descending.

| Query Param | Required | Type | Default | Description |
|---|---|---|---|---|
| `page` | No | int | `1` | Page number (1-based) |
| `limit` | No | int | `20` | Results per page (max 100) |

**Examples:**
```
GET /recommendations/                    ← first 20
GET /recommendations/?page=2             ← next 20
GET /recommendations/?page=3&limit=10   ← custom page size
Authorization: Bearer <access_token>
```

**Success `200`:**
```json
{
  "success": true,
  "message": "Recommendations fetched",
  "data": {
    "user_id": "c37a3257-dc3f-43be-9fb0-33cf918b11ff",
    "role": "trader",
    "commodity": ["rice", "cotton"],
    "qty_range": "100–500mt",
    "page": 1,
    "limit": 20,
    "total_available": 85,
    "has_more": true,
    "total": 20,
    "results": [
      {
        "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "name": "Ravi Kumar",
        "avatar_url": null,
        "role": "exporter",
        "commodity": ["rice"],
        "is_user_verified": true,
        "is_business_verified": false,
        "quantity_min": 200,
        "quantity_max": 800,
        "business_name": "Ravi Agro Pvt Ltd",
        "city": "Mumbai",
        "state": "Maharashtra",
        "msg_req_status": null,
        "follow_status": false,
        "similarity": 0.9312
      }
    ]
  }
}
```

- `total_available` — total candidates in the pool (excluding already-followed users).
- `has_more` — `false` when the last page has been reached; stop fetching on scroll.
- `total` — number of results in this page.

**Error `404`** — profile not found (onboarding not complete):
```json
{ "detail": "Profile not found — complete onboarding first" }
```

---

### `POST /recommendations/search`

Ad-hoc vector search with a custom payload. No account or token required. Useful for showing preview matches before or during signup.

**Request body:**
```json
{
  "commodity": ["rice", "cotton"],
  "role": "trader",
  "latitude_raw": 19.076,
  "longitude_raw": 72.877,
  "qty_min_mt": 100,
  "qty_max_mt": 500
}
```

**Success `200`:**
```json
{
  "success": true,
  "message": "Search results fetched",
  "data": {
    "total": 20,
    "results": [
      {
        "user_id": "a1b2c3d4-...",
        "name": "Ravi Kumar",
        "business_name": "Ravi Agro Pvt Ltd",
        "role": "exporter",
        "commodity": ["rice"],
        "is_user_verified": true,
        "is_business_verified": false,
        "quantity_min": 200,
        "quantity_max": 800,
        "city": "Mumbai",
        "state": "Maharashtra",
        "similarity": 0.9312
      }
    ]
  }
}
```

---

## 10. Shared User Object  

Every profile object across all endpoints has this base shape:

```json
{
    "user_id": "uuid",
    "name": "Ravi Traders",
    "avatar_url": "https://...",
    "role": "trader",
    "commodity": ["rice", "cotton"],
    "is_user_verified": false,
    "is_business_verified": false,
    "quantity_min": 100,
    "quantity_max": 500,
    "business_name": "Ravi Agro Pvt Ltd",
    "city": "Mumbai",
    "state": "Maharashtra",
    "msg_req_status": null,
    "follow_status": false
}
```

### `msg_req_status`

Status of the message request the **authenticated user sent** to this profile. `null` means no request has been sent.

| Value | Meaning |
|---|---|
| `null` | No message request sent |
| `"pending"` | Request sent, waiting for the other user to accept or decline |
| `"accepted"` | Request accepted — messaging is open |
| `"declined"` | Request declined |

### `follow_status`

Whether the **authenticated user is currently following** this profile.

| Value | Meaning |
|---|---|
| `false` | Not following |
| `true` | Currently following |

> **Availability:** `msg_req_status` and `follow_status` are computed from the authenticated user's perspective. They are present in **search** and **recommendations** results. Endpoints that are public or that already encode the relationship differently (followers list, following list, message-request inbox/sent) do not include these fields.

Some endpoints also add extra fields on top of the base shape:

| Endpoint | Extra fields |
|---|---|
| `GET /followers` | `followed_at` |
| `GET /following` | `followed_at` |
| `GET /message-requests/received` | `first_message`, `sent_at` |
| `GET /message-requests/sent` | `status`, `first_message`, `sent_at`, `acted_at` |
| `GET /recommendations/` | `similarity` (0–1 cosine score) |
| `POST /recommendations/search` | `similarity` (0–1 cosine score) |

---

## 11. Error Reference

| Status | When it happens |
|---|---|
| `401` | Missing or invalid Bearer token |
| `404` | Not following, no pending request found, request already acted on, or wrong receiver |
| `409` | Already following, message request already exists |
| `422` | Missing required field or wrong data type |

All errors follow FastAPI's shape:
```json
{ "detail": "Human-readable message." }
```
