# Groups Module — Developer Guide

A complete reference for group creation, membership management, join requests, permissions, invites, media uploads, and vector-based group suggestions.

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
9. [Join Request APIs](#9-join-request-apis)
10. [Member Moderation APIs](#10-member-moderation-apis)
11. [Utility APIs](#11-utility-apis)
12. [Media APIs](#12-media-apis)
13. [Suggestion API](#13-suggestion-api)
14. [Shared Objects](#14-shared-objects)
15. [Error Reference](#15-error-reference)

---

## 1. Module Overview

The groups module handles:

- **Group CRUD** — create, read, update, delete groups.
- **Membership** — join (public or private), leave, bulk-add, remove members.
- **Join Requests** — private groups require admin approval; admins manage requests from a unified inbox.
- **Moderation** — freeze/unfreeze members (admin only).
- **Permissions** — control who can post and chat inside the group.
- **Invites** — generate and use invite links.
- **Media** — upload and list images/videos inside a group.
- **Suggestions** — vector-based group recommendations using pgvector cosine ANN search.
- **Utility** — mute, favourite, report.

---

## 2. How User Identity Works

All endpoints require `Authorization: Bearer <token>`. The acting user's identity is derived exclusively from the JWT — **never** from a path or query parameter.

```
POST /api/v1/groups/
Authorization: Bearer <access_token>
```

The caller's membership context (`is_member`, `member_role`, `is_muted`, `is_favorite`) is always populated relative to the authenticated user.

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
| `group_rules` | TEXT | Optional — displayed on the group detail screen |
| `image_url` | VARCHAR(500) | Optional — uploaded via `/upload-image` first |
| `commodity` | JSONB array | e.g. `["rice", "cotton"]` |
| `target_roles` | JSONB array | e.g. `["trader", "exporter"]` |
| `region_market` | VARCHAR(200) | Optional free-text market/region name |
| `region_lat` / `region_lon` | FLOAT | Optional — used for vector embedding |
| `accessibility` | VARCHAR(20) | `public` \| `private` \| `invite_only` |
| `posting_perm` | VARCHAR(20) | `all_members` \| `admins_only` |
| `chat_perm` | VARCHAR(20) | `all_members` \| `admins_only` |
| `member_count` | INT | Maintained by service layer |
| `created_by` | UUID FK → users.id | Creator |
| `invite_link_token` | VARCHAR(100) | Generated on first invite-link request |
| `created_at` | DATETIME | |

### `group_members`

| Column | Type | Notes |
|---|---|---|
| `group_id` | UUID FK → groups.id | |
| `user_id` | UUID FK → users.id | |
| `role` | VARCHAR(20) | `admin` \| `member` |
| `is_frozen` | BOOL | Frozen members cannot send messages |
| `is_muted` | BOOL | Per-user notification mute |
| `is_favorite` | BOOL | Per-user favourite flag |
| `joined_at` | DATETIME | |

Composite PK: `(group_id, user_id)`. Ordered by `role = admin` first, then `joined_at ASC`.

### `group_join_requests`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | Auto-generated |
| `group_id` | UUID FK → groups.id CASCADE | The group being requested |
| `user_id` | UUID FK → users.id CASCADE | The user requesting to join |
| `status` | VARCHAR(20) | `pending` \| `approved` \| `rejected` |
| `created_at` | DATETIME | When the request was submitted |
| `resolved_at` | DATETIME | Nullable — filled when admin approves/rejects |
| `resolved_by` | UUID FK → users.id | Nullable — the admin who resolved it |

Indexes: `(group_id, status)` for the admin dashboard, `(user_id)` for per-user lookups.

### `group_activity_cache`

Denormalised activity counters updated by background cron.

| Column | Type | Notes |
|---|---|---|
| `group_id` | UUID PK FK → groups.id | |
| `messages_24h` | INT | Messages in the last 24 hours |
| `unique_senders_24h` | INT | |
| `active_members_7d` | INT | |
| `member_growth_7d` | INT | |
| `updated_at` | DATETIME | |

### `group_embeddings`

11-dim pgvector IS vector. Layout: `[3 commodity | 3 role | 3 geo | 2 zeros]`.

| Column | Type | Notes |
|---|---|---|
| `group_id` | UUID PK FK → groups.id | |
| `embedding` | vector(11) | HNSW index for cosine ANN search |
| `updated_at` | DATETIME | |

### `group_media`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | Auto-generated |
| `group_id` | UUID FK → groups.id CASCADE | |
| `uploaded_by` | UUID FK → users.id CASCADE | |
| `media_url` | VARCHAR(500) | Public CDN URL |
| `media_type` | VARCHAR(20) | `image` \| `video` |
| `storage_path` | VARCHAR(500) | Internal Supabase path |
| `uploaded_at` | DATETIME | |

---

## 5. File Structure

```
app/modules/groups/
  models.py    ← SQLAlchemy ORM (Group, GroupMember, GroupJoinRequest, GroupEmbedding, GroupActivityCache, GroupMedia)
  schemas.py   ← Pydantic DTOs (GroupCreate, GroupOut, GroupMemberOut, GroupJoinRequestOut, ...)
  service.py   ← All business logic
  router.py    ← FastAPI route handlers
  vector.py    ← Group embedding builder + match-reason logic
```

---

## 6. API Quick Reference

Base prefix: `/api/v1/groups`

All endpoints require `Authorization: Bearer <access_token>`.

| Method | Endpoint | Who can call | What it does |
|---|---|---|---|
| `POST` | `/upload-image` | Any verified user | Get signed upload URL for group cover image |
| `GET` | `/suggestions` | Any member | Vector-matched group suggestions |
| `GET` | `/my-pending-requests` | Any member | Aggregated pending join requests across all groups caller admins |
| `GET` | `/` | Any member | List groups with filters |
| `POST` | `/` | KYC + KYB verified only | Create a group — **201** |
| `POST` | `/join-by-link/{token}` | Any member | Join via invite token |
| `GET` | `/{group_id}` | Any member | Get group detail |
| `PATCH` | `/{group_id}` | Admin only | Update group info |
| `PATCH` | `/{group_id}/permissions` | Admin only | Update posting/chat/access rules |
| `DELETE` | `/{group_id}` | Admin only | Delete group |
| `POST` | `/{group_id}/join` | Any member | Join public group or submit request for private group |
| `DELETE` | `/{group_id}/leave` | Group member | Leave a group |
| `GET` | `/{group_id}/members` | Group member | Paginated member list (admins first) |
| `POST` | `/{group_id}/members/add` | Admin only | Bulk-add members |
| `DELETE` | `/{group_id}/members/{uid}` | Admin only | Remove a member |
| `POST` | `/{group_id}/members/{uid}/freeze` | Admin only | Freeze a member |
| `DELETE` | `/{group_id}/members/{uid}/freeze` | Admin only | Unfreeze a member |
| `GET` | `/{group_id}/join-requests` | Admin only | List join requests for a specific group |
| `POST` | `/{group_id}/join-requests/{request_id}/approve` | Admin only | Approve a join request |
| `POST` | `/{group_id}/join-requests/{request_id}/reject` | Admin only | Reject a join request |
| `POST` | `/{group_id}/mute` | Group member | Toggle notification mute |
| `POST` | `/{group_id}/favorite` | Group member | Toggle favourite |
| `GET` | `/{group_id}/invite-link` | Group member | Get or generate invite link |
| `POST` | `/{group_id}/report` | Any member | Report a group |
| `POST` | `/{group_id}/media/upload` | Group member | Get signed upload URL for group media |
| `GET` | `/{group_id}/media` | Group member | List media in a group |
| `DELETE` | `/{group_id}/media/{media_id}` | Admin or uploader | Delete a media item |

---

## 7. Group CRUD APIs

### `POST /api/v1/groups/upload-image`

**Step 1 of image upload.** Get a signed URL to upload the group cover image directly to Supabase storage. Pass the returned `image_url` in `GroupCreate.image_url` when creating the group.

| Query Param | Required | Description |
|---|---|---|
| `content_type` | Yes | `image/jpeg` \| `image/png` \| `image/webp` |

**Example:**
```
POST /api/v1/groups/upload-image?content_type=image/jpeg
Authorization: Bearer <access_token>
```

**Success `200`:**
```json
{
  "success": true,
  "message": "Group image upload URL generated",
  "data": {
    "upload_url": "https://supabase-storage.../signed-url",
    "image_url": "https://supabase-storage.../group-image/user-id/uuid.jpg",
    "content_type": "image/jpeg"
  }
}
```

After receiving this, PUT the image bytes to `upload_url` with `Content-Type: image/jpeg`, then pass `image_url` to the create/update endpoint.

---

### `POST /api/v1/groups/`

Create a new group. **Requires KYC + KYB verification.** Creator is automatically added as admin.

**Request body:**
```json
{
  "name": "Rice Traders Mumbai",
  "description": "A group for rice commodity traders in Mumbai.",
  "group_rules": "No spam. Trade-related posts only.",
  "image_url": "https://supabase-storage.../group-image/user-id/uuid.jpg",
  "commodities": ["rice"],
  "region_market": "APMC Vashi",
  "region_lat": 19.076,
  "region_lon": 72.877,
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
| `group_rules` | No | string | Displayed on group detail screen |
| `image_url` | No | string | URL from `/upload-image` |
| `commodities` | No | string[] | e.g. `["rice", "cotton"]` |
| `region_market` | No | string | Free-text market/region name |
| `region_lat` / `region_lon` | No | float | Used for vector-based suggestions |
| `accessibility` | No | string | `public` (default) \| `private` \| `invite_only` |
| `posting_perm` | No | string | `all_members` (default) \| `admins_only` |
| `chat_perm` | No | string | `all_members` (default) \| `admins_only` |
| `target_roles` | No | string[] | `trader`, `broker`, `exporter` |
| `initial_member_ids` | No | UUID[] | Added as members immediately |

**Success `201`:**
```json
{
  "success": true,
  "message": "Group created successfully",
  "data": {
    "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "name": "Rice Traders Mumbai",
    "description": "A group for rice commodity traders in Mumbai.",
    "group_rules": "No spam. Trade-related posts only.",
    "image_url": "https://supabase-storage.../group-image/...",
    "commodity": ["rice"],
    "target_roles": ["trader", "exporter"],
    "region_market": "APMC Vashi",
    "region_lat": 19.076,
    "region_lon": 72.877,
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
| `commodity` | No | string | — | Filter by commodity (exact match, e.g. `rice`) |
| `accessibility` | No | string | — | `public` \| `private` \| `invite_only` |
| `search` | No | string | — | Search by group name (case-insensitive, partial match) |
| `region_market` | No | string | — | Filter by market/region name (partial match) |
| `target_role` | No | string | — | Filter groups targeting a role (`trader` \| `broker` \| `exporter`) |
| `page` | No | int | `1` | Page number (1-based) |
| `per_page` | No | int | `20` | Results per page (max 100) |

**Examples:**
```
GET /api/v1/groups/?commodity=rice&accessibility=public
GET /api/v1/groups/?search=wheat&region_market=Mumbai
GET /api/v1/groups/?target_role=exporter&page=2
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

Get full detail for a single group including the caller's membership state and group rules.

**Success `200`** — returns a single `GroupOut` object (see [Shared Objects](#14-shared-objects)).

**Error `404`:**
```json
{ "detail": "Group not found" }
```

---

### `PATCH /api/v1/groups/{group_id}`

Update group info. **Admin only.** All fields are optional — send only what you want to change.

**Request body:**
```json
{
  "name": "Rice & Sugar Traders Mumbai",
  "description": "Updated description.",
  "group_rules": "Updated rules.",
  "image_url": "https://supabase-storage.../new-image.jpg",
  "commodities": ["rice", "sugar"],
  "region_market": "APMC Vashi",
  "region_lat": 19.076,
  "region_lon": 72.877
}
```

Updating `commodities`, `region_lat`, or `region_lon` automatically rebuilds the group's vector embedding.

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

Delete a group. **Admin only.** Cascades to memberships, join requests, media, and embeddings.

**Success `200`:**
```json
{ "success": true, "message": "Group deleted" }
```

---

## 8. Membership APIs

### `POST /api/v1/groups/{group_id}/join`

Join a group. Behaviour depends on the group's `accessibility`:

| `accessibility` | Result |
|---|---|
| `public` | Joined immediately — returns `status: "joined"` |
| `private` | Creates a pending join request — returns `status: "pending"`, admin must approve |
| `invite_only` | Rejected — use the invite link instead |

No request body required.

**Success `200` — public group:**
```json
{
  "success": true,
  "message": "Joined group",
  "data": {
    "status": "joined",
    "role": "member",
    "joined_at": "2026-05-28T10:00:00.000000+00:00"
  }
}
```

**Success `200` — private group:**
```json
{
  "success": true,
  "message": "Joined group",
  "data": {
    "status": "pending",
    "message": "Join request sent. Waiting for admin approval."
  }
}
```

**Error `403`** — invite-only group:
```json
{ "detail": "This group is invite-only. Use an invite link." }
```

**Error `409`** — already a member:
```json
{ "detail": "Already a member of this group" }
```

**Error `409`** — pending request already exists (private group):
```json
{ "detail": "Join request already pending for this group" }
```

---

### `DELETE /api/v1/groups/{group_id}/leave`

Leave a group. The last admin cannot leave — must assign another admin first.

**Success `200`:**
```json
{ "success": true, "message": "Left group" }
```

**Error `403`** — sole admin trying to leave:
```json
{ "detail": "You are the sole admin. Assign another admin before leaving." }
```

---

### `GET /api/v1/groups/{group_id}/members`

Paginated member list. **Must be a group member to view.** Admins always appear at the top, followed by regular members ordered by join date.

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
        "role": "Trader",
        "avatar_url": null,
        "is_admin": true,
        "is_user_verified": true,
        "is_business_verified": true,
        "member_role": "admin",
        "is_frozen": false,
        "is_muted": false,
        "joined_at": "2026-05-20T10:00:00.000000+00:00"
      },
      {
        "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "name": "Anita Shah",
        "role": "Exporter",
        "avatar_url": null,
        "is_admin": false,
        "is_user_verified": true,
        "is_business_verified": false,
        "member_role": "member",
        "is_frozen": false,
        "is_muted": false,
        "joined_at": "2026-05-21T09:00:00.000000+00:00"
      }
    ],
    "total": 12,
    "page": 1,
    "limit": 20
  }
}
```

- `role` — the member's professional role (Trader / Broker / Exporter).
- `member_role` — their role within the group (`admin` or `member`).
- `is_frozen` — frozen members cannot send messages in group chat.

---

### `POST /api/v1/groups/{group_id}/members/add`

Bulk-add users to a group. **Admin only.** Users already in the group are silently skipped.

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
  "data": {
    "added": ["a1b2c3d4-...", "b2c3d4e5-..."],
    "count": 2
  }
}
```

---

### `DELETE /api/v1/groups/{group_id}/members/{target_user_id}`

Remove a member from the group. **Admin only.**

**Success `200`:**
```json
{ "success": true, "message": "Member removed" }
```

**Error `404`** — user is not a member:
```json
{ "detail": "User is not a member of this group" }
```

---

## 9. Join Request APIs

These endpoints handle the approval flow for **private groups**. When a user hits `POST /{group_id}/join` on a private group, a join request is created instead of an immediate membership. Admins then approve or reject it.

---

### `GET /api/v1/groups/my-pending-requests`

**Aggregated view — admin's unified inbox.** Returns all pending join requests across every group the authenticated user admins. Scoped entirely by the JWT — no other user's requests are ever returned.

| Query Param | Type | Default | Description |
|---|---|---|---|
| `page` | int | `1` | Page number |
| `limit` | int | `20` | Per page (max 100) |

**Example:**
```
GET /api/v1/groups/my-pending-requests
Authorization: Bearer <access_token>
```

**Success `200`:**
```json
{
  "success": true,
  "message": "Pending join requests fetched",
  "data": {
    "requests": [
      {
        "id": "b3c4d5e6-f7a8-9012-bcde-f12345678901",
        "group_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
        "group_name": "Rice Traders Mumbai",
        "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "status": "pending",
        "created_at": "2026-05-28T09:30:00.000000+00:00"
      }
    ],
    "total": 1,
    "page": 1,
    "limit": 20
  }
}
```

Returns an empty list if the user admins no groups or there are no pending requests.

---

### `GET /api/v1/groups/{group_id}/join-requests`

List join requests for a **specific group**. **Admin only.** Filter by status.

| Query Param | Type | Default | Description |
|---|---|---|---|
| `status` | string | `pending` | `pending` \| `approved` \| `rejected` |
| `page` | int | `1` | Page number |
| `limit` | int | `20` | Per page (max 100) |

**Example:**
```
GET /api/v1/groups/f47ac10b-.../join-requests?status=pending
Authorization: Bearer <access_token>
```

**Success `200`:**
```json
{
  "success": true,
  "message": "Join requests fetched",
  "data": {
    "requests": [
      {
        "id": "b3c4d5e6-f7a8-9012-bcde-f12345678901",
        "group_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
        "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "status": "pending",
        "created_at": "2026-05-28T09:30:00.000000+00:00",
        "resolved_at": null,
        "resolved_by": null
      }
    ],
    "total": 1,
    "page": 1,
    "limit": 20
  }
}
```

---

### `POST /api/v1/groups/{group_id}/join-requests/{request_id}/approve`

Approve a pending join request. **Admin only.** Automatically adds the user as a member and increments `member_count`.

**Example:**
```
POST /api/v1/groups/f47ac10b-.../join-requests/b3c4d5e6-.../approve
Authorization: Bearer <access_token>
```

**Success `200`:**
```json
{
  "success": true,
  "message": "Join request approved",
  "data": {
    "request_id": "b3c4d5e6-...",
    "status": "approved"
  }
}
```

**Error `409`** — request already resolved:
```json
{ "detail": "Request already approved" }
```

---

### `POST /api/v1/groups/{group_id}/join-requests/{request_id}/reject`

Reject a pending join request. **Admin only.** The user is not added to the group.

**Success `200`:**
```json
{
  "success": true,
  "message": "Join request rejected",
  "data": {
    "request_id": "b3c4d5e6-...",
    "status": "rejected"
  }
}
```

---

## 10. Member Moderation APIs

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

## 11. Utility APIs

### `POST /api/v1/groups/{group_id}/mute`

Toggle mute for the authenticated user. Muting suppresses notifications — does not affect posting or viewing.

**Success `200`:**
```json
{
  "success": true,
  "message": "Mute toggled",
  "data": { "is_muted": true }
}
```

---

### `POST /api/v1/groups/{group_id}/favorite`

Toggle favourite for the authenticated user.

**Success `200`:**
```json
{
  "success": true,
  "message": "Favorite toggled",
  "data": { "is_favorite": true }
}
```

---

### `GET /api/v1/groups/{group_id}/invite-link`

Get the invite link for a group. If no token exists yet, one is generated. **Group member only.**

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

Share `join_url` directly or use `invite_link_token` for a deep link.

---

### `POST /api/v1/groups/join-by-link/{token}`

Join a group via its invite token. Bypasses the private-group approval flow — having the token is enough.

**Success `200`:**
```json
{
  "success": true,
  "message": "Joined group via invite link",
  "data": {
    "group_id": "f47ac10b-...",
    "group_name": "Rice Traders Mumbai",
    "role": "member",
    "joined_at": "2026-05-28T10:00:00.000000+00:00"
  }
}
```

**Error `404`** — invalid token:
```json
{ "detail": "Invalid or expired invite link" }
```

---

### `POST /api/v1/groups/{group_id}/report`

Report a group for manual review.

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

## 12. Media APIs

### `POST /api/v1/groups/{group_id}/media/upload`

**Step 1 of media upload.** Get a signed URL to upload an image or video. Creates a `GroupMedia` record immediately and returns `media_id`. **Must be a group member.**

| Query Param | Required | Description |
|---|---|---|
| `content_type` | Yes | `image/jpeg` \| `image/png` \| `image/webp` \| `video/mp4` \| `video/quicktime` \| `video/webm` |

**Example:**
```
POST /api/v1/groups/f47ac10b-.../media/upload?content_type=video/mp4
Authorization: Bearer <access_token>
```

**Success `200`:**
```json
{
  "success": true,
  "message": "Group media upload URL generated",
  "data": {
    "media_id": "d5e6f7a8-b9c0-1234-efab-c56789012345",
    "upload_url": "https://supabase-storage.../signed-url",
    "media_url": "https://supabase-storage.../group-media/group-id/media-id.mp4",
    "media_type": "video",
    "expires_at": "2026-05-28T10:30:00.000000+00:00"
  }
}
```

After receiving, PUT the file bytes to `upload_url` with the matching `Content-Type` header.

---

### `GET /api/v1/groups/{group_id}/media`

List all media uploaded to a group, ordered by upload date descending. **Must be a group member.**

| Query Param | Type | Default | Description |
|---|---|---|---|
| `page` | int | `1` | Page number |
| `limit` | int | `20` | Per page (max 100) |

**Success `200`:**
```json
{
  "success": true,
  "message": "Group media fetched",
  "data": {
    "media": [
      {
        "id": "d5e6f7a8-b9c0-1234-efab-c56789012345",
        "group_id": "f47ac10b-...",
        "uploaded_by": "c37a3257-...",
        "media_url": "https://supabase-storage.../group-media/...",
        "media_type": "video",
        "uploaded_at": "2026-05-28T10:05:00.000000+00:00"
      }
    ],
    "total": 8,
    "page": 1,
    "limit": 20
  }
}
```

---

### `DELETE /api/v1/groups/{group_id}/media/{media_id}`

Delete a media item. **Admin or the original uploader only.** Also deletes the file from Supabase storage (best-effort — DB record is always removed).

**Success `200`:**
```json
{ "success": true, "message": "Media deleted" }
```

**Error `403`:**
```json
{ "detail": "Only admins or the uploader can delete media" }
```

---

## 13. Suggestion API

### `GET /api/v1/groups/suggestions`

Returns paginated group recommendations using **pgvector HNSW cosine ANN search**. Groups are matched against the user's commodity profile, role, and business location.

| Query Param | Type | Default | Description |
|---|---|---|---|
| `page` | int | `1` | Page number (1-based) |
| `limit` | int | `20` | Results per page (max 100) |

**How it works:**
1. Loads the caller's profile (commodity, role, business lat/lon).
2. Builds a WANT vector using `build_query_vector()`.
3. Runs HNSW ANN cosine search against `group_embeddings` — excludes private groups and groups the user already belongs to.
4. Activity reranking: blends vector similarity (75%) + activity score (25%) from `group_activity_cache`.
5. Returns results with human-readable `match_reasons`.

**Success `200`:**
```json
{
  "success": true,
  "message": "Group suggestions fetched",
  "data": {
    "results": [
      {
        "group": {
          "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
          "name": "Rice Traders Mumbai",
          "description": "A group for rice commodity traders in Mumbai.",
          "group_rules": "No spam. Trade-related posts only.",
          "image_url": null,
          "commodity": ["rice"],
          "target_roles": ["trader", "exporter"],
          "region_market": "APMC Vashi",
          "region_lat": 19.076,
          "region_lon": 72.877,
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

- `match_score` — 0–1 composite score (higher is better).
- `match_reasons` — human-readable strings. Render as chips/tags on the frontend.

**Error `422`** — business profile not set up:
```json
{ "detail": "Business profile not set up — complete onboarding to get group suggestions." }
```

---

## 14. Shared Objects

### `GroupOut` — standard group object

Returned by create, get, list, update, and suggestion endpoints.

```json
{
  "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "name": "Rice Traders Mumbai",
  "description": "A group for rice commodity traders.",
  "group_rules": "No spam. Trade-related posts only.",
  "image_url": "https://supabase-storage.../group-image/...",
  "commodity": ["rice"],
  "target_roles": ["trader", "exporter"],
  "region_market": "APMC Vashi",
  "region_lat": 19.076,
  "region_lon": 72.877,
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
  "role": "Trader",
  "avatar_url": null,
  "is_admin": true,
  "is_user_verified": true,
  "is_business_verified": true,
  "member_role": "admin",
  "is_frozen": false,
  "is_muted": false,
  "joined_at": "2026-05-20T10:00:00.000000+00:00"
}
```

- `role` — professional role (Trader / Broker / Exporter).
- `member_role` — role within this group (`admin` or `member`).

---

### `GroupJoinRequestOut` — join request item (per-group view)

```json
{
  "id": "b3c4d5e6-f7a8-9012-bcde-f12345678901",
  "group_id": "f47ac10b-...",
  "user_id": "a1b2c3d4-...",
  "status": "pending",
  "created_at": "2026-05-28T09:30:00.000000+00:00",
  "resolved_at": null,
  "resolved_by": null
}
```

---

### `AdminPendingRequestOut` — join request item (aggregated inbox)

```json
{
  "id": "b3c4d5e6-f7a8-9012-bcde-f12345678901",
  "group_id": "f47ac10b-...",
  "group_name": "Rice Traders Mumbai",
  "user_id": "a1b2c3d4-...",
  "status": "pending",
  "created_at": "2026-05-28T09:30:00.000000+00:00"
}
```

`group_name` is included so the frontend can display which group the request is for without a second call.

---

## 15. Error Reference

All errors follow FastAPI's standard shape:
```json
{ "detail": "Human-readable message." }
```

| Status | When it happens |
|---|---|
| `401` | Missing or invalid Bearer token |
| `403` | Not an admin / not a member / not KYC+KYB verified (group creation) / only admins or uploader can delete media |
| `404` | Group not found / profile not found / member not found / invalid invite token / join request not found / media not found |
| `409` | Already a member / join request already pending / join request already resolved |
| `422` | Missing required field, wrong data type, or unsupported media content-type |
| `503` | Supabase storage error during image/media upload |
