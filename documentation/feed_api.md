# Home Feed Module — API Documentation

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
> The acting user's identity is derived from the JWT token — do not pass `user_id` as a query parameter.  
> See [auth_and_access_control.md](auth_and_access_control.md) for the full auth model.

---

## Table of Contents

1. [Get Home Feed](#1-get-home-feed)
2. [Submit Engagement Signals](#2-submit-engagement-signals)
3. [Feed Item Object](#feed-item-object)
4. [Cursor Object](#cursor-object)
5. [Content Type Reference](#content-type-reference)
6. [Engagement Signal Reference](#engagement-signal-reference)
7. [Error Reference](#error-reference)
8. [Testing Checklist](#testing-checklist)

---

## Feed Item Object

Every item in the feed `items` array has this outer shape:

```json
{
  "item_type": "post",
  "item_id": "42",
  "content_type_label": "post",
  "is_priority": false,
  "data": { ... }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `item_type` | string | One of: `"post"`, `"news"`, `"group"`, `"connection"` |
| `item_id` | string | Unique ID of the item (string, even if originally an int) |
| `content_type_label` | string | Display label — see [Content Type Reference](#content-type-reference) |
| `is_priority` | bool | `true` = this item was pinned by the priority queue (show a badge / highlight) |
| `data` | object | The full item payload — shape depends on `item_type` (see below) |

---

### `data` shape — Post item (`item_type: "post"`)

```json
{
  "id": 42,
  "profile_id": 3,
  "category_id": 1,
  "commodity_id": 2,
  "caption": "Cotton prices are up this week.",
  "image_url": null,
  "like_count": 5,
  "comment_count": 2,
  "save_count": 1,
  "share_count": 0,
  "view_count": 14,
  "is_liked": false,
  "is_saved": true,
  "allow_comments": true,
  "created_at": "2026-04-17T10:30:00+00:00"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | int | Post ID |
| `profile_id` | int | Profile that created the post |
| `category_id` | int | 1–5 (Market Update / Knowledge / Discussion / Deal / Other) |
| `commodity_id` | int | 1–3 (Rice / Cotton / Sugar) |
| `caption` | string | Post text |
| `image_url` | string \| null | Optional image |
| `like_count` | int | Total likes |
| `comment_count` | int | Total comments |
| `save_count` | int | Total saves |
| `share_count` | int | Total shares |
| `view_count` | int | Total views |
| `is_liked` | bool | Whether the requesting user has liked this post |
| `is_saved` | bool | Whether the requesting user has saved this post |
| `allow_comments` | bool | Whether comments are enabled |
| `created_at` | datetime | ISO 8601 UTC |

---

### `data` shape — News item (`item_type: "news"`)

```json
{
  "id": "a1b2c3d4-...",
  "title": "Global cotton output forecast revised downward",
  "summary": "The ICAC has revised its 2026 cotton production forecast...",
  "url": "https://example.com/article",
  "image_url": "https://example.com/image.jpg",
  "published_at": "2026-04-17T08:00:00+00:00",
  "severity": 8.5,
  "commodities": ["cotton"],
  "regions": ["india", "global"],
  "role_impact": "Cotton traders should expect tighter supply in Q3...",
  "cluster_id": 3,
  "is_breaking": true
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID string | Article ID |
| `title` | string | Article headline |
| `summary` | string \| null | Short summary |
| `url` | string | Full article URL |
| `image_url` | string \| null | Article thumbnail |
| `published_at` | datetime | ISO 8601 UTC |
| `severity` | float \| null | 1–10 severity score (≥ 8 = breaking) |
| `commodities` | string[] | Affected commodities |
| `regions` | string[] | Affected regions |
| `role_impact` | string \| null | Impact summary tailored to the user's role (trader / broker / exporter) |
| `cluster_id` | int \| null | News cluster (1–6) |
| `is_breaking` | bool | Present and `true` only on priority-pinned breaking news |

---

### `data` shape — Group Activity item (`item_type: "group"`)

```json
{
  "id": 88,
  "profile_id": 5,
  "caption": "Check out this new rice deal opportunity.",
  "image_url": null,
  "like_count": 3,
  "comment_count": 1,
  "save_count": 0,
  "share_count": 0,
  "view_count": 9,
  "category_id": 4,
  "commodity_id": 1,
  "created_at": "2026-04-17T09:15:00+00:00",
  "group_id": "f3a1...",
  "group_name": "Rice Traders India",
  "velocity_score": 2.45
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | int | Post ID |
| `profile_id` | int | Author's profile ID |
| `caption` | string | Post text |
| `group_id` | UUID string | Group this post belongs to |
| `group_name` | string | Group display name |
| `velocity_score` | float | Engagement velocity used for ranking |
| (other post fields) | — | Same as Post item |

---

### `data` shape — Connection Suggestion item (`item_type: "connection"`)

```json
{
  "user_id": "uuid-of-suggested-user",
  "profile_id": 12,
  "name": "Rajesh Mehta",
  "business_name": "Mehta Agro Exports",
  "role_id": 3,
  "latitude": 21.14,
  "longitude": 79.08
}
```

| Field | Type | Description |
|-------|------|-------------|
| `user_id` | UUID string | Suggested user's UUID |
| `profile_id` | int | Suggested user's profile ID |
| `name` | string | Full name |
| `business_name` | string \| null | Business or company name |
| `role_id` | int | 1 = Trader, 2 = Broker, 3 = Exporter |
| `latitude` | float | Location latitude |
| `longitude` | float | Location longitude |

---

## Cursor Object

The cursor tracks pagination state across all four content sources independently. Pass it back on every subsequent page request.

```json
{
  "post_cursor": "2026-04-17T10:30:00+00:00|42",
  "news_cursor": "2026-04-17T08:00:00+00:00|a1b2c3d4-...",
  "group_cursor": "2026-04-17T09:15:00+00:00|88",
  "connection_cursor": 3,
  "page_num": 2
}
```

| Field | Type | Description |
|-------|------|-------------|
| `post_cursor` | string \| null | `"ISO_TIMESTAMP\|post_id"` — last seen post |
| `news_cursor` | string \| null | `"ISO_TIMESTAMP\|news_id"` — last seen article |
| `group_cursor` | string \| null | `"ISO_TIMESTAMP\|post_id"` — last seen group post |
| `connection_cursor` | int | Offset for connection suggestions |
| `page_num` | int | Current page number (1-based) |

> **How to use:** On the first request, do not send `cursor`. The response will contain a cursor. Pass that cursor (JSON-encoded as a string) in the `cursor` query parameter on every subsequent request.

---

## Content Type Reference

| `item_type` | `content_type_label` | Description |
|-------------|----------------------|-------------|
| `post` | `"post"` | Regular feed post |
| `post` | `"post"` (with `is_priority: true`) | Unseen post from a followed user (pinned, last 6 h) |
| `news` | `"news"` | News article personalised to user's commodities |
| `news` | `"breaking_news"` (with `is_priority: true`) | Breaking news, severity ≥ 8, last 3 h |
| `group` | `"group_activity"` | Post from a group the user is a member of |
| `connection` | `"connection"` | Suggested user to connect with |

---

## 1. Get Home Feed

**`GET /feed/home`**  
**`GET /feed/home?cursor={cursor_json}`**

Returns one page (20 items) of the blended home feed.

- **First call** (no `cursor`): priority pins are resolved and prepended — unseen posts from followed users (last 6 h) + breaking news (severity ≥ 8, last 3 h).
- **Subsequent calls**: pass `cursor` from the previous response to get the next page.

### Query Parameters

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `cursor` | string | No | JSON-encoded cursor from the previous response |

> Identity comes from the `Authorization: Bearer <token>` header, not a query param.

### Response — `200 OK`

```json
{
  "success": true,
  "message": "Feed fetched successfully",
  "data": {
    "items": [
      {
        "item_type": "post",
        "item_id": "42",
        "content_type_label": "post",
        "is_priority": true,
        "data": {
          "id": 42,
          "profile_id": 3,
          "category_id": 1,
          "commodity_id": 2,
          "caption": "Cotton prices are up this week.",
          "image_url": null,
          "like_count": 5,
          "comment_count": 2,
          "save_count": 1,
          "share_count": 0,
          "view_count": 14,
          "is_liked": false,
          "is_saved": true,
          "allow_comments": true,
          "created_at": "2026-04-17T10:30:00+00:00"
        }
      },
      {
        "item_type": "news",
        "item_id": "a1b2c3d4-e5f6-...",
        "content_type_label": "breaking_news",
        "is_priority": true,
        "data": {
          "id": "a1b2c3d4-e5f6-...",
          "title": "Global cotton output forecast revised downward",
          "summary": "The ICAC has revised its 2026 cotton production forecast...",
          "url": "https://example.com/article",
          "image_url": "https://example.com/image.jpg",
          "published_at": "2026-04-17T08:00:00+00:00",
          "severity": 8.5,
          "commodities": ["cotton"],
          "regions": ["india", "global"],
          "role_impact": "Cotton traders should expect tighter supply in Q3...",
          "cluster_id": 3,
          "is_breaking": true
        }
      },
      {
        "item_type": "connection",
        "item_id": "uuid-of-suggested-user",
        "content_type_label": "connection",
        "is_priority": false,
        "data": {
          "user_id": "uuid-of-suggested-user",
          "profile_id": 12,
          "name": "Rajesh Mehta",
          "business_name": "Mehta Agro Exports",
          "role_id": 3,
          "latitude": 21.14,
          "longitude": 79.08
        }
      }
    ],
    "cursor": {
      "post_cursor": "2026-04-17T10:30:00+00:00|42",
      "news_cursor": "2026-04-17T08:00:00+00:00|a1b2c3d4-...",
      "group_cursor": null,
      "connection_cursor": 1,
      "page_num": 2
    },
    "has_more": true,
    "weights_used": {
      "post": 0.5,
      "news": 0.25,
      "group": 0.15,
      "connection": 0.1
    }
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `items` | array | Up to 20 feed items for this page |
| `cursor` | object | Pass this (JSON-encoded) as `cursor` in the next request |
| `has_more` | bool | `true` if more pages are available |
| `weights_used` | object | Content-type mixing weights used for this page (for debugging) |

### Errors

| Status | Reason |
|--------|--------|
| `400` | `cursor` parameter is not valid JSON |
| `404` | No profile found for the given `user_id` |

---

### Pagination Flow

```
First request
  GET /feed/home?user_id=<uuid>
  → returns items (page 1) + cursor

Second request
  GET /feed/home?user_id=<uuid>&cursor={"post_cursor":"...","page_num":2,...}
  → returns items (page 2) + updated cursor

Third request
  GET /feed/home?user_id=<uuid>&cursor={"post_cursor":"...","page_num":3,...}
  → returns items (page 3) + updated cursor

When has_more is false → no more pages.
```

> **Important:** The cursor must be passed as a JSON string in the query parameter — not as separate fields.  
> Example: `cursor={"post_cursor":"2026-04-17T10:30:00%2B00:00|42","page_num":2,...}`

---

### Content Mixing Rules

The feed mixes four content types per page using weighted random selection.

**Default weights by page:**

| Page | Posts | News | Groups | Connections |
|------|-------|------|--------|-------------|
| 1–2 | 50% | 25% | 15% | 10% |
| 3–5 | 55% | 15% | 20% | 10% |
| 6+ | 65% | 5% | 15% | 15% |

**Consecutive cap** — no content type appears more than N times in a row:

| Type | Max consecutive |
|------|----------------|
| Posts | 3 |
| News | 2 |
| Group Activity | 1 |
| Connection Suggestions | 1 |

---

### Priority Pins (First Load Only)

On the first page load (no cursor), up to 7 items are pinned at the top with `is_priority: true`:

| Type | Condition | Max |
|------|-----------|-----|
| Post | Unseen post from a followed user, created in last **6 hours** | 5 |
| News | Severity ≥ 8, published in last **3 hours**, matches user's commodities | 2 |

When ≤ 3 priority items remain in the list, the feed begins interleaving normal items between them (every 3rd slot) for a smooth transition.

---

## 2. Submit Engagement Signals

**`POST /feed/engagement`**

Sends a batch of user engagement signals to the backend. Currently the signals are acknowledged — session-taste weight adaptation will be enabled in a future release.

> **When to call:** Send after every ~10 viewport events (item enters/exits screen), or when the user performs an explicit action (like, save, share).

### Auth

`Authorization: Bearer <token>` required. No query params for identity.

### Request Body

```json
{
  "signals": [
    {
      "item_id": "42",
      "item_type": "post",
      "action": "dwell",
      "dwell_ms": 5500
    },
    {
      "item_id": "42",
      "item_type": "post",
      "action": "like"
    },
    {
      "item_id": "a1b2c3d4-...",
      "item_type": "news",
      "action": "skip",
      "dwell_ms": 900
    },
    {
      "item_id": "uuid-of-suggested-user",
      "item_type": "connection",
      "action": "connection_dismiss"
    }
  ]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `signals` | array | Yes | List of engagement signal objects |
| `signals[].item_id` | string | Yes | ID of the item (use `item_id` from the feed response) |
| `signals[].item_type` | string | Yes | `"post"` \| `"news"` \| `"group"` \| `"connection"` |
| `signals[].action` | string | Yes | See [Engagement Signal Reference](#engagement-signal-reference) |
| `signals[].dwell_ms` | int | Conditional | Required for `dwell`, `strong_dwell`, `skip` — time in milliseconds |

### Response — `200 OK`

```json
{
  "success": true,
  "message": "Engagement recorded",
  "data": {
    "acknowledged": true,
    "signals_processed": 4
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `acknowledged` | bool | Always `true` |
| `signals_processed` | int | Number of signals received |

---

## Engagement Signal Reference

### Passive (viewport-based)

| Action | `dwell_ms` required | Trigger condition | Weight |
|--------|---------------------|-------------------|--------|
| `skip` | Yes | Item visible for **< 1.5 s** | −1 |
| `dwell` | Yes | Item visible for **4–10 s** | +2 |
| `strong_dwell` | Yes | Item visible for **> 10 s** | +2 (×1.3 bonus) |

> Items visible 1.5–4 s are **neutral** — do not send a signal for them.

### Explicit (user action)

| Action | Applies to | Weight | Notes |
|--------|------------|--------|-------|
| `like` | post, news, group | +3 | Toggle action on the item |
| `save` | post, news, group | +5 | Strongest positive signal |
| `share` | post, news, group | +4 | — |
| `comment` | post, group | +4 | — |
| `connection_accept` | connection | +3 | User accepted the suggestion |
| `connection_dismiss` | connection | −1 | User dismissed the suggestion |

---

## Error Reference

All errors follow this shape:

```json
{
  "detail": "Profile not found for user 00000000-0000-0000-0000-000000000000"
}
```

| HTTP Status | Meaning | When it happens |
|-------------|---------|-----------------|
| `200` | OK | Feed page or engagement acknowledged |
| `400` | Bad Request | `cursor` is not valid JSON |
| `404` | Not Found | No profile exists for the given `user_id` |
| `422` | Unprocessable Entity | Missing required query parameter (`user_id`) or invalid UUID format |

---

## Quick Reference — All Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/feed/home` | Bearer token | Get home feed page |
| `POST` | `/feed/engagement` | Bearer token | Submit engagement signals |

---

## Testing Checklist

### Setup
- [ ] Server running: `uvicorn main:app --reload` (from `/backend`)
- [ ] DB migrated: `alembic upgrade head`
- [ ] At least one user + profile exists — note the UUID from `users` table
- [ ] At least a few posts and news articles exist in the DB

### First Load
- [ ] **GET /feed/home** with a valid `user_id` — expect `200`, `items` array, `cursor`, `has_more`
- [ ] Verify `items` contains a mix of content types (post / news / group / connection)
- [ ] Verify priority items have `is_priority: true` and appear at the top
- [ ] Verify `weights_used` sums to ~1.0

### Pagination
- [ ] **Page 2** — pass `cursor` from page 1 — expect `200`, different items, incremented `page_num`
- [ ] **Page 3** — pass `cursor` from page 2 — verify `page_num` = 3 and weights shifted
- [ ] When `has_more` is `false` — next request returns empty `items`

### Engagement
- [ ] **POST /feed/engagement** with a `signals` array — expect `200`, `signals_processed` matches count
- [ ] Send empty `signals: []` — expect `200`, `signals_processed: 0`

### Error Cases
- [ ] **GET /feed/home** with unknown user (valid token, no profile) — expect `404`
- [ ] **GET /feed/home** with invalid `cursor` string (not JSON) — expect `400`
- [ ] **GET /feed/home** without `Authorization` header — expect `401`

### Runner Script

```bash
# Interactive feed tester (needs an existing user UUID)
cd backend
python scripts/test_feed.py --user-id <uuid>
```

---

## Integration Notes for Frontend

1. **First load**: Call `GET /feed/home` (no `cursor`) with `Authorization: Bearer <token>`. Store the returned `cursor` object.

2. **Scroll to bottom (load more)**: Call `GET /feed/home?cursor=<json_encoded_cursor>` with the same token. Replace the stored cursor with the new one.

3. **Pull-to-refresh**: Discard the cursor and call `GET /feed/home` again (no cursor). This re-runs the priority pin resolution.

4. **Rendering by type**:
   - `item_type: "post"` / `content_type_label: "post"` → render as a post card
   - `item_type: "news"` / `content_type_label: "news"` → render as a news card
   - `item_type: "news"` / `content_type_label: "breaking_news"` + `is_priority: true` → render with breaking badge
   - `item_type: "group"` / `content_type_label: "group_activity"` → render as post card with group label
   - `item_type: "connection"` / `content_type_label: "connection"` → render as people suggestion card
   - Any item with `is_priority: true` → show a priority / pinned indicator

5. **Engagement signals**: Track viewport dwell time per item. Batch signals and call `POST /feed/engagement` every ~10 items or on explicit actions (like, save, share).

6. **Cursor encoding**: JSON-encode the cursor object and pass it as a plain string query parameter. Most HTTP clients handle URL encoding automatically.
