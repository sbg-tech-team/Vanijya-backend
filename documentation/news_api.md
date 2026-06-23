# News API — v2

**Base URL:** `https://vanijyaa-backend.onrender.com`  
**Auth:** `Authorization: Bearer <token>` required on all endpoints.

All responses use the standard envelope:

```json
{ "success": true, "message": "...", "data": { ... } }
```

The `data` field contains the payload described for each endpoint below.

---

## What changed from v1

| Status | Endpoints |
|--------|-----------|
| Changed (path or response shape) | `/news/feed`, `/news/saved`, `/news/{id}`, `/news/{id}/like`, `/news/{id}/save`, `/news/{id}/share` |
| New | `/news/feed/saved`, `/news/feed/global`, `/news/feed/domestic`, `/news/feed/regional`, `/news/articles/{id}`, `/news/interactions/batch`, `/news/interactions/like/{id}`, `/news/interactions/save/{id}`, `/news/interactions/share/{id}` |
| Removed | `/news/search`, `/news/my/taste`, `/news/my/history`, `/news/{id}/engage`, `/news/{id}/comment`, `/news/{id}/comments` |

---

## Feed endpoints

### GET /news/feed

Returns a cursor-paginated list of enriched articles, ordered by platform arrival time (newest first), role-scored.

**Query params:**

| Param | Type | Default | Notes |
|-------|------|---------|-------|
| `limit` | int | 20 | Max 50 |
| `cursor` | string | — | Returned by the previous page response. Omit on first call. |

**Response `data`:**

```json
{
  "items": [
    {
      "article_id": "uuid",
      "title": "Wheat MSP hiked by ₹150 ahead of rabi season",
      "image_url": "string | null",
      "source_name": "The Hindu BusinessLine",
      "time_on_platform": "2h",
      "platform_arrived_at": "2024-11-01T10:30:00",
      "summary_bullets": [
        "MSP raised to ₹2,275/quintal, up 7.1% from last year",
        "Decision comes ahead of peak procurement window"
      ],
      "primary_factor": "policy",
      "geo_category": "domestic",
      "impact_direction": "bullish",
      "impact_score": 7.8,
      "like_count": 24,
      "share_count": 8,
      "is_liked": false,
      "is_saved": false,
      "role_score": 0.91,
      "final_score": 0.91
    }
  ],
  "cursor": {
    "next_cursor": "base64encodedstring",
    "has_more": true
  }
}
```

**Field reference:**

| Field | Type | Notes |
|-------|------|-------|
| `article_id` | UUID | Use this as the ID for all interaction endpoints |
| `time_on_platform` | string | Human-readable age: `"1h"`, `"Yesterday"`, `"3 days ago"` |
| `summary_bullets` | `string[] \| null` | AI-generated bullets. `null` if enrichment is pending |
| `primary_factor` | string | One of: `price`, `policy`, `weather`, `logistics`, `demand`, `supply`, `currency`, `global`, `regulatory`, `other` |
| `geo_category` | string | `global`, `domestic`, or `regional` |
| `impact_direction` | string | `bullish`, `bearish`, or `neutral` |
| `impact_score` | float | 0–10 severity of impact |
| `role_score` | float | How relevant this article is to the user's role |
| `next_cursor` | `string \| null` | Pass as `?cursor=` on the next call. `null` means last page |

---

### GET /news/feed/saved

Articles saved by the current user, most-recently-saved first.

Same query params (`limit`, `cursor`) and same `data` shape as `/news/feed`.

---

### GET /news/feed/global
### GET /news/feed/domestic
### GET /news/feed/regional

Filtered feeds by `geo_category`. Same query params and `data` shape as `/news/feed`.

---

### GET /news/articles/{article_id}

Full detail view for a single article.

**Response `data`:**

Everything in the feed card above, plus:

| Field | Type | Notes |
|-------|------|-------|
| `description` | `string \| null` | Full article description from the source |
| `article_url` | string | Link to original article |
| `source_url` | `string \| null` | Publisher homepage |
| `published_at` | datetime | Source publication timestamp |
| `impact_explanation` | `string \| null` | AI explanation of why this article matters |
| `impact_factor` | `string \| null` | Which factor drives the impact |
| `factor_scores` | `list \| null` | Per-factor breakdown |
| `view_count` | `int \| null` | Total views on platform |
| `save_count` | `int \| null` | Total saves on platform |

---

## Interaction endpoints

### POST /news/interactions/batch

Send passive interaction events collected client-side (impressions, dwell time, opens, share taps). Call this when the user leaves the feed or at regular intervals — do not call per-event.

**Request body:**

```json
{
  "events": [
    {
      "article_id": "uuid",
      "event_type": "impression",
      "value_ms": null,
      "occurred_at": "2024-11-01T10:32:00Z"
    },
    {
      "article_id": "uuid",
      "event_type": "dwell",
      "value_ms": 18000,
      "occurred_at": "2024-11-01T10:33:00Z"
    }
  ]
}
```

| Field | Type | Notes |
|-------|------|-------|
| `event_type` | string | `impression`, `dwell`, `open_article`, `share_tap` |
| `value_ms` | `int \| null` | Required when `event_type` is `dwell` |
| `occurred_at` | datetime | Client-side timestamp (ISO 8601, UTC). Events older than 2 hours are dropped. |

Max 200 events per batch.

**Response `data`:**

```json
{ "accepted": 8, "dropped": 1 }
```

---

### POST /news/interactions/like/{article_id}

Toggle like on an article. Call once to like, call again to unlike.

**Response `data`:**

```json
{ "article_id": "uuid", "is_liked": true }
```

---

### POST /news/interactions/save/{article_id}

Toggle save on an article.

**Response `data`:**

```json
{ "article_id": "uuid", "is_saved": true }
```

---

### POST /news/interactions/share/{article_id}

Record a share event.

**Query param:** `platform` (optional) — `whatsapp`, `copy`, `twitter`, etc.

**Response `data`:**

```json
{ "article_id": "uuid", "platform": "whatsapp" }
```

---

## Removed endpoints

| Endpoint | Status |
|----------|--------|
| `GET /news/search` | Removed — not in v2 |
| `GET /news/my/taste` | Paused — taste scoring deferred |
| `GET /news/my/history` | Paused |
| `POST /news/{id}/engage` | Replaced by `POST /news/interactions/batch` |
| `POST /news/{id}/comment` | Removed — comments not in v2 |
| `GET /news/{id}/comments` | Removed — comments not in v2 |

---

## Migration quick-reference

| Old | New |
|-----|-----|
| `GET /news/saved` | `GET /news/feed/saved` |
| `GET /news/{id}` | `GET /news/articles/{id}` |
| `POST /news/{id}/like` | `POST /news/interactions/like/{id}` |
| `POST /news/{id}/save` | `POST /news/interactions/save/{id}` |
| `POST /news/{id}/share` | `POST /news/interactions/share/{id}` |
| `POST /news/{id}/engage` | `POST /news/interactions/batch` |
| `data.sections[].articles[]` | `data.items[]` |
| `article.id` | `article.article_id` |
| `article.url` | `article.article_url` (detail only) |
| `article.summary` | `article.summary_bullets` (list) |
| `article.liked` | `article.is_liked` |
| `article.saved` | `article.is_saved` |
| `{ liked, like_count }` (like response) | `{ article_id, is_liked }` |
| `{ saved }` (save response) | `{ article_id, is_saved }` |
| `{ share_count }` (share response) | `{ article_id, platform }` |
