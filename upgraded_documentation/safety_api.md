# Safety Module — Developer Guide

A complete reference for **blocking** users and **reporting** users, groups, or posts for moderation.

**Base URL:** `https://vanijyaa-backend.onrender.com`

**Interactive docs (Swagger):** `https://vanijyaa-backend.onrender.com/docs`

---

## Table of Contents

1. [Module Overview](#1-module-overview)
2. [Path Convention](#2-path-convention)
3. [Database Schema](#3-database-schema)
4. [File Structure](#4-file-structure)
5. [API Quick Reference](#5-api-quick-reference)
6. [Block APIs](#6-block-apis)
7. [Report APIs](#7-report-apis)
8. [Cross-Module Helpers](#8-cross-module-helpers)
9. [Shared Objects](#9-shared-objects)
10. [Error Reference](#10-error-reference)

---

## 1. Module Overview

The safety module handles two independent concerns:

- **Blocks** — a user can block another user. Blocks are **one-directional** (`blocker → blocked`) and stored as a single row keyed on the pair. Other modules consume the block list to suppress DMs, feed entries, and other interactions.
- **Reports** — a user can submit a moderation report against a **user**, **group**, or **post**. Reports are write-once per `(reporter, target)` and enter a moderation queue with a `pending` status for backend review.

Both features are persisted; there is no in-memory state.

---

## 2. Path Convention & Auth

The router is mounted at the **`/safety`** prefix (no `/api/v1` segment).

**The acting user is always derived from the JWT** via the `get_current_user_id`
dependency — never from a path or query parameter. Every endpoint requires
`Authorization: Bearer <access_token>`.

| Placeholder | Meaning |
|---|---|
| `{target_id}` | The user being **blocked** or **reported** |

The only path placeholder is `{target_id}`; the blocker/reporter identity comes from the token.

### Pagination

List endpoints (`/blocked`, `/reports`) accept page-based pagination, matching the rest of the codebase:

| Query param | Default | Bounds |
|---|---|---|
| `page` | `1` | `≥ 1` |
| `limit` | `20` | `1–100` |

Paginated responses include `total` (full count), `page`, and `limit` alongside the item array.

---

## 3. Database Schema

### `user_blocks`

One-directional block. A row means `blocker_id` has blocked `blocked_id`.

| Column | Type | Notes |
|---|---|---|
| `blocker_id` | UUID FK → users.id CASCADE | Part of composite PK — the user who blocked |
| `blocked_id` | UUID FK → users.id CASCADE | Part of composite PK — the user who was blocked |
| `blocked_at` | DATETIME (tz-aware) | Defaults to UTC now |

Composite PK: `(blocker_id, blocked_id)` — guarantees a pair can only be blocked once. Deleting either user cascades the row away.

### `user_reports`

Moderation record. `target_type + target_id` is **polymorphic** — it points at a user, group, or post row **without a hard FK** (the target may be deleted before review).

| Column | Type | Notes |
|---|---|---|
| `id` | INT PK | Auto-increment |
| `reporter_id` | UUID FK → users.id CASCADE | The user filing the report |
| `target_type` | VARCHAR(20) | `user` \| `group` \| `post` |
| `target_id` | UUID | Polymorphic target — no FK constraint |
| `reason` | VARCHAR(50) | `spam` \| `harassment` \| `inappropriate_content` \| `scam` \| `impersonation` \| `other` |
| `description` | TEXT | Optional, free text (≤ 1000 chars) |
| `status` | VARCHAR(20) | `pending` \| `reviewed` \| `actioned` \| `dismissed` — defaults to `pending` |
| `created_at` | DATETIME (tz-aware) | Defaults to UTC now |
| `reviewed_at` | DATETIME (tz-aware) | Nullable — filled when moderation resolves it |

Unique constraint `uq_report_per_target` on `(reporter_id, target_type, target_id)` — a user can only report a given target once.

Migration: `alembic/versions/40326de17936_add_safety_block_and_report_tables.py`.

---

## 4. File Structure

```
app/modules/safety/
├── __init__.py
├── models.py      # UserBlock, UserReport ORM models
├── schemas.py     # ReportRequest + validation enums
├── service.py     # block/report logic, zero FastAPI imports
└── router.py      # /safety endpoints
```

The service layer is FastAPI-free and exposes reusable helpers (`is_blocked`, `either_blocked`) for other modules — see [§8](#8-cross-module-helpers).

---

## 5. API Quick Reference

All endpoints require `Authorization: Bearer <access_token>`.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/safety/block/{target_id}` | Block a user |
| `DELETE` | `/safety/block/{target_id}` | Unblock a user |
| `GET` | `/safety/blocked` | List everyone you have blocked (paginated) |
| `GET` | `/safety/block/status/{target_id}` | Is target blocked? (button state) |
| `POST` | `/safety/report` | Submit a report (user/group/post) |
| `GET` | `/safety/reports` | List your submitted reports (paginated) |

---

## 6. Block APIs

### 6.1 Block a user

```
POST /safety/block/{target_id}
```

Blocks `target_id` on behalf of the authenticated user.

**Rules**
- Cannot block yourself → `400`.
- Already blocked → `409`.

**Response `200`**
```json
{
  "status": "blocked",
  "blocked_id": "8b1f...c4"
}
```

---

### 6.2 Unblock a user

```
DELETE /safety/block/{target_id}
```

Removes an existing block.

**Rules**
- No block exists → `404`.

**Response `200`**
```json
{
  "status": "unblocked",
  "blocked_id": "8b1f...c4"
}
```

---

### 6.3 List blocked users

```
GET /safety/blocked?page=1&limit=20
```

Returns everyone the authenticated user has blocked, **newest first**, with each
blocked user's profile `name` and `avatar_url` joined in (both `null` if the
target has no profile row).

| Query param | Default | Bounds |
|---|---|---|
| `page` | `1` | `≥ 1` |
| `limit` | `20` | `1–100` |

**Response `200`**
```json
{
  "blocked": [
    {
      "blocked_id": "8b1f...c4",
      "blocked_at": "2026-06-25T10:12:03Z",
      "name": "Acme Traders",
      "avatar_url": "https://.../avatars/8b1f.png"
    },
    {
      "blocked_id": "1c9a...02",
      "blocked_at": "2026-06-20T08:45:11Z",
      "name": "Ravi Kumar",
      "avatar_url": null
    }
  ],
  "total": 2,
  "page": 1,
  "limit": 20
}
```

---

### 6.4 Check block status

```
GET /safety/block/status/{target_id}
```

Drives the block/unblock button state on a profile screen.

**Response `200`**
```json
{
  "blocker_id": "a3d2...91",
  "blocked_id": "8b1f...c4",
  "is_blocked": true
}
```

---

## 7. Report APIs

### 7.1 Submit a report

```
POST /safety/report
```

**Request body** ([`ReportRequest`](#9-shared-objects))
```json
{
  "target_type": "post",
  "target_id": "f17c...aa",
  "reason": "scam",
  "description": "Asking for advance payment off-platform."
}
```

| Field | Required | Validation |
|---|---|---|
| `target_type` | ✅ | one of `user` \| `group` \| `post` |
| `target_id` | ✅ | UUID |
| `reason` | ✅ | one of `spam` \| `harassment` \| `inappropriate_content` \| `scam` \| `impersonation` \| `other` |
| `description` | ❌ | string, ≤ 1000 chars |

**Rules**
- Reporting yourself (`target_type == "user"` and `target_id == user_id`) → `400`.
- Already reported this exact target → `409`.

**Response `200`**
```json
{
  "id": 42,
  "target_type": "post",
  "target_id": "f17c...aa",
  "reason": "scam",
  "status": "pending",
  "created_at": "2026-06-25T10:30:00Z"
}
```

> Validation on `target_type` / `reason` is enforced by Pydantic regex patterns, so an invalid enum returns FastAPI's standard `422` body before the handler runs.

---

### 7.2 List my reports

```
GET /safety/reports?page=1&limit=20
```

Returns all reports submitted by the authenticated user, **newest first**.

| Query param | Default | Bounds |
|---|---|---|
| `page` | `1` | `≥ 1` |
| `limit` | `20` | `1–100` |

**Response `200`**
```json
{
  "reports": [
    {
      "id": 42,
      "target_type": "post",
      "target_id": "f17c...aa",
      "reason": "scam",
      "status": "pending",
      "created_at": "2026-06-25T10:30:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "limit": 20
}
```

---

## 8. Cross-Module Helpers

`service.py` exposes two FastAPI-free helpers other modules import to enforce blocks. They are **not** HTTP endpoints.

| Helper | Signature | Returns |
|---|---|---|
| `is_blocked` | `is_blocked(db, blocker_id, blocked_id)` | `True` if `blocker_id` has blocked `blocked_id` (directional). |
| `either_blocked` | `either_blocked(db, user_a, user_b)` | `True` if **either** user has blocked the other. Use for DM / feed guards where a block in either direction should suppress interaction. |

**Typical usage**
```python
from app.modules.safety import service as safety

if safety.either_blocked(db, sender_id, recipient_id):
    raise HTTPException(403, "Interaction blocked.")
```

---

## 9. Shared Objects

### `ReportRequest`
```python
{
  "target_type": str,   # "user" | "group" | "post"
  "target_id":   UUID,
  "reason":      str,    # spam | harassment | inappropriate_content | scam | impersonation | other
  "description": str?    # optional, max 1000 chars
}
```

### Enum reference

| Set | Values |
|---|---|
| `VALID_TARGET_TYPES` | `user`, `group`, `post` |
| `VALID_REASONS` | `spam`, `harassment`, `inappropriate_content`, `scam`, `impersonation`, `other` |
| Report `status` | `pending`, `reviewed`, `actioned`, `dismissed` |

---

## 10. Error Reference

| Status | When | Detail |
|---|---|---|
| `400` | Blocking yourself | `Cannot block yourself.` |
| `400` | Reporting yourself (user target) | `Cannot report yourself.` |
| `404` | Unblocking a pair with no block row | `Block not found.` |
| `409` | Blocking someone already blocked | `User is already blocked.` |
| `409` | Reporting a target already reported | `You have already reported this.` |
| `422` | `target_type` or `reason` fails the regex pattern | FastAPI validation body |
