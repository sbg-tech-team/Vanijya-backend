# Groups Module — Developer Guide

A complete reference for group creation, membership management, permissions, invites, and vector-based group suggestions.

**Base URL:** `https://vanijyaa-backend.onrender.com`

**Interactive docs (Swagger):** `https://vanijyaa-backend.onrender.com/docs`

---

## Table of Contents

1. [Module Overview](#1-module-overview)
2. [How User Identity Works](#2-how-user-identity-works)
3. [Verification Gate](#3-verification-gate)
4. [Database Schema](#4-database-schema)
5. [File Structure](#5-file-structure)
6. [API Quick Reference](#6-api-quick-reference)
7. [Group CRUD APIs](#7-group-crud-apis)
8. [Membership APIs](#8-membership-apis)
9. [Member Moderation APIs](#9-member-moderation-apis)
10. [Utility APIs](#10-utility-apis)
11. [Suggestion API](#11-suggestion-api)
12. [Shared Objects](#12-shared-objects)
13. [Error Reference](#13-error-reference)

---

## 1. Module Overview

The groups module handles:

- **Group CRUD** — create, read, update, delete groups.
- **Membership** — join, leave, add members by admin, remove members.
- **Moderation** — freeze/unfreeze members (admin only).
- **Permissions** — control who can post and chat inside the group.
- **Invites** — generate and use invite links.
- **Suggestions** — vector-based group recommendations using pgvector cosine ANN search.
- **Utility** — mute, favourite, report.

---

## 2. How User Identity Works

All mutating endpoints require `Authorization: Bearer <token>`. The acting user's identity is derived exclusively from the JWT — **never** from a path or query parameter.

```
POST /api/v1/groups/
Authorization: Bearer <access_token>
```

Read endpoints (`GET /`, `GET /:id`, `GET /:id/members`, `GET /suggestions`) also require a token — the caller's membership context is used to populate `is_member`, `member_role`, etc.

---

## 3. Verification Gate

**Only users who have passed both KYC (`is_user_verified = true`) and KYB (`is_business_verified = true`) can create a group.**

Attempting to create a group without full verification returns `403`:

```json
{ "detail": "Only fully verified users (KYC + KYB) can create groups. Complete profile verification first." }
```

Joining an existing group has no verification requirement.

---

## 4. Database Schema

### `groups`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | Auto-generated |
| `name` | VARCHAR(200) | Required, min 3 chars |
| `description` | TEXT | Optional |
| `group_rules` | TEXT | Optional |
| `icon_url` | VARCHAR | Optional |
| `commodity` | JSONB array | e.g. `["rice", "cotton"]` |
| `target_roles` | JSONB array | e.g. `["trader", "exporter"]` |
| `region_market` | VARCHAR | Optional free-text market name |
| `region_lat` / `region_lon` | FLOAT | Optional — used for vector embedding |
| `category` | VARCHAR | `commodity_trading` \| `news` \| `network` |
| `accessibility` | VARCHAR | `public` \| `private` \| `invite_only` |
| `posting_perm` | VARCHAR | `all_members` \| `admins_only` |
| `chat_perm` | VARCHAR | `all_members` \| `admins_only` |
| `member_count` | INT | Maintained by service layer |
| `created_by` | UUID FK → users.id | Creator |
| `invite_link_token` | VARCHAR | Generated on first invite-link request |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

### `group_members`

| Column | Type | Notes |
|---|---|---|
| `group_id` | UUID FK → groups.id | |
| `user_id` | UUID FK → users.id | |
| `role` | VARCHAR | `admin` \| `member` |
| `is_frozen` | BOOL | Frozen members cannot send messages |
| `is_muted` | BOOL | Per-user notification mute |
| `is_favorite` | BOOL | Per-user favourite flag |
| `joined_at` | TIMESTAMPTZ | |

Composite PK: `(group_id, user_id)`.

---

## 5. File Structure

```
app/modules/groups/
  models.py    ← SQLAlchemy ORM (Group, GroupMember, GroupEmbedding, GroupActivityCache)
  schemas.py   ← Pydantic DTOs (GroupCreate, GroupOut, GroupMemberOut, ...)
  service.py   ← All business logic
  router.py    ← FastAPI route handlers (18 endpoints)
  vector.py    ← Group embedding builder + match-reason logic
```

---

## 6. API Quick Reference

Base prefix: `/api/v1/groups`

All endpoints require `Authorization: Bearer <access_token>`.

| Method | Endpoint | Who can call | What it does |
|---|---|---|---|
| `GET` | `/suggestions` | Any member | Vector-matched group suggestions |
| `GET` | `/` | Any member | List groups with optional filters |
| `POST` | `/` | KYC + KYB verified only | Create a group — **201** |
| `POST` | `/join-by-link/{token}` | Any member | Join via invite token |
| `GET` | `/{group_id}` | Any member | Get group detail |
| `PATCH` | `/{group_id}` | Admin only | Update group info |
| `PATCH` | `/{group_id}/permissions` | Admin only | Update posting/chat/access rules |
| `POST` | `/{group_id}/join` | Any member | Join a public group |
| `DELETE` | `/{group_id}/leave` | Group member | Leave a group |
| `GET` | `/{group_id}/members` | Group member | Paginated member list |
| `POST` | `/{group_id}/members/add` | Admin only | Bulk-add members |
| `DELETE` | `/{group_id}/members/{uid}` | Admin only | Remove a member |
| `POST` | `/{group_id}/members/{uid}/freeze` | Admin only | Freeze a member |
| `DELETE` | `/{group_id}/members/{uid}/freeze` | Admin only | Unfreeze a member |
| `POST` | `/{group_id}/mute` | Group member | Toggle notification mute |
| `POST` | `/{group_id}/favorite` | Group member | Toggle favourite |
| `GET` | `/{group_id}/invite-link` | Admin only | Get or generate invite link |
| `POST` | `/{group_id}/report` | Any member | Report a group |

---

## 7. Group CRUD APIs

### `POST /api/v1/groups/`

Create a new group. **Requires KYC + KYB verification.** Creator is automatically added as admin.

**Request body:**
```json
{
  "name": "Rice Traders Mumbai",
  "description": "A group for rice commodity traders in Mumbai.",
  "group_rules": "No spam. Trade-related posts only.",
  "commodities": ["rice"],
  "region_market": "APMC Vashi",
  "region_lat": 19.076,
  "region_lon": 72.877,
  "category": "commodity_trading",
  "accessibility": "public",
  "posting_perm": "all_members",
  "chat_perm": "all_members",
  "target_roles": ["trader", "exporter"],
  "initial_member_ids": ["a1b2c3d4-e5f6-7890-abcd-ef1234567890"]
}
```

| Field | Required | Type | Notes |
|---|---|---|---|
| `name` | Yes | string | 3–200 characters |
| `description` | No | string | |
| `group_rules` | No | string | |
| `commodities` | No | string[] | e.g. `["rice", "cotton"]` |
| `region_market` | No | string | |
| `region_lat` / `region_lon` | No | float | Used for vector-based suggestions |
| `category` | No | string | `commodity_trading` \| `news` \| `network` |
| `accessibility` | No | string | `public` (default) \| `private` \| `invite_only` |
| `posting_perm` | No | string | `all_members` (default) \| `admins_only` |
| `chat_perm` | No | string | `all_members` (default) \| `admins_only` |
| `target_roles` | No | string[] | `trader`, `broker`, `exporter` |
| `initial_member_ids` | No | UUID[] | Users added as members immediately |

**Success `201`:**
```json
{
  "success": true,
  "message": "Group created successfully",
  "data": {
    "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "name": "Rice Traders Mumbai",
    "description": "A group for rice commodity traders in Mumbai.",
    "icon_url": null,
    "commodity": ["rice"],
    "target_roles": ["trader", "exporter"],
    "region_market": "APMC Vashi",
    "region_lat": 19.076,
    "region_lon": 72.877,
    "category": "commodity_trading",
    "accessibility": "public",
    "posting_perm": "all_members",
    "chat_perm": "all_members",
    "member_count": 2,
    "created_by": "c37a3257-dc3f-43be-9fb0-33cf918b11ff",
    "created_at": "2026-05-20T10:00:00.000000+00:00",
    "is_member": true,
    "member_role": "admin",
    "is_muted": false,
    "is_favorite": false
  }
}
```

**Error `403`** — not fully verified:
```json
{ "detail": "Only fully verified users (KYC + KYB) can create groups. Complete profile verification first." }
```

---

### `GET /api/v1/groups/`

List groups with optional filters. Caller's membership context is included in each group object.

| Query Param | Required | Type | Default | Description |
|---|---|---|---|---|
| `commodity` | No | string | — | Filter by commodity name (exact) |
| `accessibility` | No | string | — | `public`, `private`, or `invite_only` |
| `page` | No | int | `1` | Page number (1-based) |
| `per_page` | No | int | `20` | Results per page (max 100) |

**Example:**
```
GET /api/v1/groups/?commodity=rice&accessibility=public&page=1
Authorization: Bearer <access_token>
```

**Success `200`:**
```json
{
  "success": true,
  "message": "Groups fetched",
  "data": {
    "groups": [ /* array of GroupOut objects */ ],
    "total": 42,
    "page": 1,
    "per_page": 20
  }
}
```

---

### `GET /api/v1/groups/{group_id}`

Get full detail for a single group, including the caller's membership state.

**Example:**
```
GET /api/v1/groups/f47ac10b-58cc-4372-a567-0e02b2c3d479
Authorization: Bearer <access_token>
```

**Success `200`** — returns a single `GroupOut` object (same shape as create response).

**Error `404`:**
```json
{ "detail": "Group not found" }
```

---

### `PATCH /api/v1/groups/{group_id}`

Update group info. **Admin only.**

**Request body** (all fields optional — only send what you want to change):
```json
{
  "name": "Rice & Sugar Traders Mumbai",
  "description": "Updated description.",
  "icon_url": "https://...",
  "commodities": ["rice", "sugar"],
  "region_market": "APMC Vashi",
  "region_lat": 19.076,
  "region_lon": 72.877,
  "category": "commodity_trading"
}
```

**Success `200`** — returns the updated `GroupOut` object.

**Error `403`:**
```json
{ "detail": "Admin access required" }
```

---

### `PATCH /api/v1/groups/{group_id}/permissions`

Update access and posting rules. **Admin only.**

**Request body** (all fields optional):
```json
{
  "accessibility": "invite_only",
  "posting_perm": "admins_only",
  "chat_perm": "all_members"
}
```

| Field | Allowed values |
|---|---|
| `accessibility` | `public` \| `private` \| `invite_only` |
| `posting_perm` | `all_members` \| `admins_only` |
| `chat_perm` | `all_members` \| `admins_only` |

**Success `200`** — returns updated `GroupOut` object.

---

### `DELETE /api/v1/groups/{group_id}`

Delete a group. **Admin only.** Cascades to memberships and embeddings.

**Success `200`:**
```json
{ "success": true, "message": "Group deleted" }
```

---

## 8. Membership APIs

### `POST /api/v1/groups/{group_id}/join`

Join a public group. No body required.

**Success `200`:**
```json
{
  "success": true,
  "message": "Joined group",
  "data": { "group_id": "f47ac10b-...", "status": "joined" }
}
```

**Error `409`** — already a member:
```json
{ "detail": "Already a member of this group" }
```

**Error `403`** — group is `private` or `invite_only`:
```json
{ "detail": "This group requires an invitation" }
```

---

### `DELETE /api/v1/groups/{group_id}/leave`

Leave a group. The last admin cannot leave (must transfer admin role first).

**Success `200`:**
```json
{ "success": true, "message": "Left group" }
```

**Error `403`** — last admin trying to leave:
```json
{ "detail": "Cannot leave — you are the only admin. Transfer admin role first." }
```

---

### `GET /api/v1/groups/{group_id}/members`

Paginated member list. **Must be a group member to view.**

| Query Param | Type | Default | Description |
|---|---|---|---|
| `page` | int | `1` | Page number |
| `limit` | int | `20` | Per page (max 100) |

**Success `200`:**
```json
{
  "success": true,
  "message": "Members fetched",
  "data": {
    "members": [
      {
        "user_id": "c37a3257-dc3f-43be-9fb0-33cf918b11ff",
        "name": "Ravi Traders",
        "role": "trader",
        "avatar_url": null,
        "is_admin": true,
        "is_user_verified": true,
        "is_business_verified": true,
        "member_role": "admin",
        "is_frozen": false,
        "is_muted": false,
        "joined_at": "2026-05-20T10:00:00.000000+00:00"
      }
    ],
    "total": 12,
    "page": 1,
    "limit": 20
  }
}
```

---

### `POST /api/v1/groups/{group_id}/members/add`

Bulk-add users to a group. **Admin only.**

**Request body:**
```json
{
  "user_ids": [
    "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "b2c3d4e5-f6a7-8901-bcde-f12345678901"
  ]
}
```

**Success `200`:**
```json
{
  "success": true,
  "message": "Members added",
  "data": { "added": 2 }
}
```

---

### `DELETE /api/v1/groups/{group_id}/members/{target_user_id}`

Remove a member. **Admin only.** Cannot remove another admin.

**Success `200`:**
```json
{ "success": true, "message": "Member removed" }
```

**Error `403`** — trying to remove an admin:
```json
{ "detail": "Cannot remove another admin" }
```

---

## 9. Member Moderation APIs

### `POST /api/v1/groups/{group_id}/members/{target_user_id}/freeze`

Freeze a member — they cannot send messages in the group. **Admin only.**

**Success `200`:**
```json
{
  "success": true,
  "message": "Member frozen",
  "data": { "user_id": "a1b2c3d4-...", "is_frozen": true }
}
```

---

### `DELETE /api/v1/groups/{group_id}/members/{target_user_id}/freeze`

Unfreeze a member. **Admin only.**

**Success `200`:**
```json
{
  "success": true,
  "message": "Member unfrozen",
  "data": { "user_id": "a1b2c3d4-...", "is_frozen": false }
}
```

---

## 10. Utility APIs

### `POST /api/v1/groups/{group_id}/mute`

Toggle mute for the authenticated user. Muting suppresses notifications — does not affect posting or viewing.

**Success `200`:**
```json
{
  "success": true,
  "message": "Mute toggled",
  "data": { "group_id": "f47ac10b-...", "is_muted": true }
}
```

---

### `POST /api/v1/groups/{group_id}/favorite`

Toggle favourite for the authenticated user. Affects ordering in the group list on the frontend.

**Success `200`:**
```json
{
  "success": true,
  "message": "Favorite toggled",
  "data": { "group_id": "f47ac10b-...", "is_favorite": true }
}
```

---

### `GET /api/v1/groups/{group_id}/invite-link`

Get the invite link token for a group. If no token exists yet, one is generated. **Admin only.**

**Success `200`:**
```json
{
  "success": true,
  "message": "Invite link ready",
  "data": {
    "invite_link_token": "a3f8b1c2d9e4f5a6",
    "join_url": "https://vanijyaa-backend.onrender.com/api/v1/groups/join-by-link/a3f8b1c2d9e4f5a6"
  }
}
```

Share `join_url` directly or use `invite_link_token` to construct a deep link in the app.

---

### `POST /api/v1/groups/join-by-link/{token}`

Join a group via its invite token. Works for `invite_only` and `private` groups (no approval needed — the token is the gate).

**Example:**
```
POST /api/v1/groups/join-by-link/a3f8b1c2d9e4f5a6
Authorization: Bearer <access_token>
```

**Success `200`:**
```json
{
  "success": true,
  "message": "Joined group via invite link",
  "data": { "group_id": "f47ac10b-...", "status": "joined" }
}
```

**Error `404`** — invalid or expired token:
```json
{ "detail": "Invalid invite link" }
```

---

### `POST /api/v1/groups/{group_id}/report`

Report a group. Submitted for manual review by the platform team.

**Request body:**
```json
{
  "reason": "spam",
  "details": "Posts unrelated commodity promotions every hour."
}
```

**Success `200`:**
```json
{
  "success": true,
  "message": "Report submitted — our team will review it",
  "data": {
    "group_id": "f47ac10b-...",
    "reason": "spam",
    "status": "submitted"
  }
}
```

---

## 11. Suggestion API

### `GET /api/v1/groups/suggestions`

Returns paginated group recommendations for the authenticated user using **pgvector HNSW cosine ANN search**. Groups are matched against the user's commodity profile, role, and location.

| Query Param | Type | Default | Description |
|---|---|---|---|
| `page` | int | `1` | Page number (1-based) |
| `limit` | int | `20` | Results per page (max 100) |

**How it works:**
1. Loads the caller's profile (commodity, role, business location).
2. Builds a WANT vector using `build_query_vector()`.
3. Runs HNSW ANN cosine search against `group_embeddings`.
4. Scores each candidate using `compute_final_score()` (vector similarity + activity score).
5. Returns results with human-readable `match_reasons`.

**Success `200`:**
```json
{
  "success": true,
  "message": "Group suggestions fetched",
  "data": {
    "suggestions": [
      {
        "group": {
          "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
          "name": "Rice Traders Mumbai",
          "description": "A group for rice commodity traders in Mumbai.",
          "icon_url": null,
          "commodity": ["rice"],
          "target_roles": ["trader", "exporter"],
          "region_market": "APMC Vashi",
          "region_lat": 19.076,
          "region_lon": 72.877,
          "category": "commodity_trading",
          "accessibility": "public",
          "posting_perm": "all_members",
          "chat_perm": "all_members",
          "member_count": 34,
          "created_by": "c37a3257-dc3f-43be-9fb0-33cf918b11ff",
          "created_at": "2026-05-10T08:00:00.000000+00:00",
          "is_member": false,
          "member_role": null,
          "is_muted": false,
          "is_favorite": false
        },
        "match_score": 0.87,
        "match_reasons": ["trades rice", "active in Mumbai region", "matches exporter role"]
      }
    ],
    "total": 8,
    "page": 1,
    "limit": 20
  }
}
```

- `match_score` — 0–1 composite score (vector similarity + activity). Higher is better.
- `match_reasons` — human-readable strings explaining why this group was suggested. Render as chips/tags on the frontend.

---

## 12. Shared Objects

### `GroupOut` — standard group object

Returned by create, get, list, update, and suggestions.

```json
{
  "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "name": "Rice Traders Mumbai",
  "description": "A group for rice commodity traders.",
  "icon_url": null,
  "commodity": ["rice"],
  "target_roles": ["trader", "exporter"],
  "region_market": "APMC Vashi",
  "region_lat": 19.076,
  "region_lon": 72.877,
  "category": "commodity_trading",
  "accessibility": "public",
  "posting_perm": "all_members",
  "chat_perm": "all_members",
  "member_count": 34,
  "created_by": "c37a3257-...",
  "created_at": "2026-05-10T08:00:00.000000+00:00",
  "is_member": true,
  "member_role": "admin",
  "is_muted": false,
  "is_favorite": true
}
```

`is_member`, `member_role`, `is_muted`, and `is_favorite` are always relative to the **authenticated caller**. Non-members get `is_member: false`, `member_role: null`.

---

### `GroupMemberOut` — member list item

```json
{
  "user_id": "c37a3257-...",
  "name": "Ravi Traders",
  "role": "trader",
  "avatar_url": null,
  "is_admin": true,
  "is_user_verified": true,
  "is_business_verified": false,
  "member_role": "admin",
  "is_frozen": false,
  "is_muted": false,
  "joined_at": "2026-05-20T10:00:00.000000+00:00"
}
```

- `is_user_verified` — `true` if the member has passed KYC (personal identity).
- `is_business_verified` — `true` if the member has passed KYB (business verification).
- `is_frozen` — frozen members cannot send messages in group chat.

---

## 13. Error Reference

All errors follow FastAPI's standard shape:
```json
{ "detail": "Human-readable message." }
```

| Status | When it happens |
|---|---|
| `401` | Missing or invalid Bearer token |
| `403` | Not an admin, not a member, or not KYC+KYB verified (for group creation) |
| `404` | Group not found, profile not found, invalid invite token |
| `409` | Already a member, group name conflict |
| `422` | Missing required field or wrong data type (e.g. name too short) |
