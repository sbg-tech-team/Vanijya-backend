# News Module — API Documentation

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

## How the News Feed Works

1. **Ingestion** — RSS feeds are fetched every 20 min. Each article is classified by Gemini AI into one of 10 clusters with a severity score, commodity tags, and region tags.
2. **Personalisation** — On your first `/feed` call, default taste weights are seeded from your role (trader/broker/exporter). These update hourly based on your engagement.
3. **Scoring** — Every article is scored using: `severity × role_weight × commodity_match × region_match × recency × source_credibility × taste_boost × social_boost`
4. **Feed sections** — The response always has 5 sections: Breaking, For You, Trending, Worth Knowing, Government.

---

## Reference Data

### News Clusters (assigned by Gemini AI)

| cluster_id | Name |
|---|---|
| 1 | Policy & Regulation |
| 2 | Geopolitical & Macro Shocks |
| 3 | Supply-side Disruptions |
| 4 | Financial & Market Mechanics |
| 5 | Structural & Industrial Shifts |
| 6 | Long-term Demand Trends |
| 7 | Market Participation & Deal Flow |
| 8 | Price Volatility & Sentiment |
| 9 | Local Operational Events |
| 10 | Indirect / General News |

### Roles

| role string | Mapped from profile role_id |
|---|---|
| `trader` | role_id = 1 |
| `broker` | role_id = 2 |
| `exporter` | role_id = 3 |

### Engagement Action Types

| action_type | Description |
|---|---|
| `view` | Article was shown on screen |
| `click` | User tapped to open article |
| `dwell` | User spent time reading (send `dwell_time_s`) |
| `like` | Use the `/like` endpoint instead |
| `save` | Use the `/save` endpoint instead |
| `comment` | Use the `/comment` endpoint instead |
| `share_out` | Use the `/share` endpoint instead |
| `skip` | User scrolled past |

---

## Table of Contents

1. [Get Personalised Feed](#1-get-personalised-feed)
2. [Search News](#2-search-news)
3. [Get Single Article](#3-get-single-article)
4. [Record Engagement](#4-record-engagement)
5. [Like / Unlike Article](#5-like--unlike-article)
6. [Save / Unsave Article](#6-save--unsave-article)
7. [Share Article](#7-share-article)
8. [Post a Comment](#8-post-a-comment)
9. [Get Comments](#9-get-comments)
10. [Get Taste Profile](#10-get-taste-profile)
11. [Get Engagement History](#11-get-engagement-history)
12. [Article Object Reference](#12-article-object-reference)
13. [Error Reference](#13-error-reference)

---

## 12. Article Object Reference

Every endpoint that returns an article includes this shape:

```json
{
  "id": "3f8a2c1d-9e74-4b1a-8d3f-2c1d9e744b1a",
  "title": "Wheat MSP hiked by ₹150 per quintal ahead of rabi season",
  "summary": "The government announced a hike in the minimum support price...",
  "url": "https://economictimes.com/...",
  "image_url": "https://...",
  "published_at": "2026-04-18T09:30:00",

  "cluster_id": 1,
  "severity": 8.5,
  "commodities": ["wheat"],
  "regions": ["punjab", "haryana"],
  "scope": "national",
  "direction_tags": ["upward", "support"],
  "horizon": "short",

  "source_name": "Economic Times Markets",
  "source_credibility": 1.1,
  "source_category": "wire",

  "trader_impact": "Traders may face higher procurement costs for wheat.",
  "broker_impact": "Brokers should anticipate increased trading activity.",
  "exporter_impact": "Exporters might see reduced margins due to higher domestic prices.",
  "liked": false,
  "saved": false,
  "like_count": 42,

  "comment_count": 7,
  "share_count": 15
}
```

---

## 1. Get Personalised Feed

Returns 5 sections of ranked articles personalised to the user's role, commodities, and taste profile.

**`GET /news/feed`**

### Query Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `user_id` | UUID | Yes | Acting user's UUID |
| `state` | string | No | User's state e.g. `punjab` (used for region matching) |
| `scope` | string | No | `local` / `state` / `national` / `global` — default `national` |

> Role and commodities are fetched automatically from the user's profile. No need to pass them.

### Example Request

```
GET https://vanijyaa-backend.onrender.com/news/feed?user_id=<uuid>&scope=national
```

### Response `200 OK`

```json
{
  "success": true,
  "message": "Feed fetched successfully",
  "data": {
    "sections": [
      {
        "key": "right_now",
        "label": "Right Now",
        "articles": [ ...Article objects... ]
      },
      {
        "key": "for_you_today",
        "label": "For You Today",
        "articles": [ ...Article objects... ]
      },
      {
        "key": "trending",
        "label": "Trending in Your Network",
        "articles": [ ...Article objects... ]
      },
      {
        "key": "worth_knowing",
        "label": "Worth Knowing",
        "articles": [ ...Article objects... ]
      },
      {
        "key": "government",
        "label": "From Government Sources",
        "articles": [ ...Article objects... ]
      }
    ]
  }
}
```

### Section Logic

| Section key | Max articles | Logic |
|---|---|---|
| `right_now` | 3 | Breaking news: cluster 1 or 2 AND severity ≥ 8.0 |
| `for_you_today` | 12 | Top scored articles for this user |
| `trending` | 5 | Articles trending in user's segment (`role:commodity:state`) |
| `worth_knowing` | 5 | Medium severity articles (4.0–7.9) |
| `government` | 3 | Articles from government sources |

### Error

| Code | Reason |
|---|---|
| `404` | Profile not found for this user |

---

## 2. Search News

Full-text search on article titles and summaries.

**`GET /news/search`**

### Query Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `q` | string | No | Search query e.g. `wheat price` |
| `commodity` | string | No | Filter by commodity name e.g. `wheat` |
| `page` | int | No | Page number, default `1` |
| `per_page` | int | No | Results per page, default `20`, max `100` |

### Example Request

```
GET https://vanijyaa-backend.onrender.com/news/search?q=wheat+price&page=1&per_page=10
```

### Response `200 OK`

```json
{
  "success": true,
  "message": "Search results",
  "data": [ ...Array of Article objects... ]
}
```

> Articles older than 72 hours are excluded from search results.

---

## 3. Get Single Article

Fetch full details of one article. Pass `user_id` to also get `liked` and `saved` status.

**`GET /news/{article_id}`**

### Path Parameters

| Parameter | Type | Description |
|---|---|---|
| `article_id` | UUID | Article ID |

### Query Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `user_id` | UUID | No | Pass to get personalised `liked`/`saved` flags |

### Example Request

```
GET https://vanijyaa-backend.onrender.com/news/3f8a2c1d-9e74-4b1a-8d3f-2c1d9e744b1a?user_id=<uuid>
```

### Response `200 OK`

```json
{
  "success": true,
  "message": "Article fetched",
  "data": { ...Article object... }
}
```

### Errors

| Code | Reason |
|---|---|
| `404` | Article not found |

---

## 4. Record Engagement

Log a user interaction on an article. Call this when the user views, clicks, or dwells on an article. For like/save/share/comment use the dedicated endpoints.

**`POST /news/{article_id}/engage`**

### Query Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `user_id` | UUID | Yes | Acting user's UUID |

### Request Body

```json
{
  "action_type": "dwell",
  "dwell_time_s": 45,
  "segment_id": "trader:wheat:punjab"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `action_type` | string | Yes | `view` / `click` / `dwell` / `skip` |
| `dwell_time_s` | int | No | Seconds spent reading — required when `action_type` is `dwell` |
| `segment_id` | string | No | Format: `role:commodity:state` e.g. `trader:wheat:punjab` |

> Only send `dwell_time_s` when `action_type` is `dwell`. Dwell events with < 12 seconds are ignored in the taste update algorithm.

### Response `201 Created`

```json
{
  "success": true,
  "message": "Engagement recorded",
  "data": null
}
```

### Errors

| Code | Reason |
|---|---|
| `400` | Invalid `action_type` |
| `404` | Article not found |

---

## 5. Like / Unlike Article

Toggles the like on an article. Call once to like, call again to unlike.

**`POST /news/{article_id}/like`**

### Query Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `user_id` | UUID | Yes | Acting user's UUID |

### Example Request

```
POST https://vanijyaa-backend.onrender.com/news/3f8a2c1d-9e74-4b1a-8d3f-2c1d9e744b1a/like?user_id=<uuid>
```

### Response `200 OK`

```json
{
  "success": true,
  "message": "Like toggled",
  "data": {
    "liked": true,
    "like_count": 43
  }
}
```

| Field | Description |
|---|---|
| `liked` | `true` if the user now likes the article, `false` if unliked |
| `like_count` | Updated total like count for the article |

### Errors

| Code | Reason |
|---|---|
| `404` | Article not found |

---

## 6. Save / Unsave Article

Toggles the save on an article. Call once to save, call again to unsave.

**`POST /news/{article_id}/save`**

### Query Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `user_id` | UUID | Yes | Acting user's UUID |

### Example Request

```
POST https://vanijyaa-backend.onrender.com/news/3f8a2c1d-9e74-4b1a-8d3f-2c1d9e744b1a/save?user_id=<uuid>
```

### Response `200 OK`

```json
{
  "success": true,
  "message": "Save toggled",
  "data": {
    "saved": true
  }
}
```

| Field | Description |
|---|---|
| `saved` | `true` if the article is now saved, `false` if unsaved |

### Errors

| Code | Reason |
|---|---|
| `404` | Article not found |

---

## 7. Share Article

Records a share event and returns the updated share count. Each call adds one share — not a toggle.

**`POST /news/{article_id}/share`**

### Query Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `user_id` | UUID | Yes | Acting user's UUID |

### Example Request

```
POST https://vanijyaa-backend.onrender.com/news/3f8a2c1d-9e74-4b1a-8d3f-2c1d9e744b1a/share?user_id=<uuid>
```

### Response `200 OK`

```json
{
  "success": true,
  "message": "Shared successfully",
  "data": {
    "share_count": 16
  }
}
```

### Errors

| Code | Reason |
|---|---|
| `404` | Article not found |

---

## 8. Post a Comment

Post a comment on an article.

**`POST /news/{article_id}/comment`**

### Query Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `user_id` | UUID | Yes | Acting user's UUID |

### Request Body

```json
{
  "text": "Prices in Punjab will rise this week."
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `text` | string | Yes | Comment text — min 1 char, max 1000 chars |

### Response `201 Created`

```json
{
  "success": true,
  "message": "Comment posted",
  "data": null
}
```

### Errors

| Code | Reason |
|---|---|
| `404` | Article not found |
| `422` | Text too long (> 1000 chars) or empty |

---

## 9. Get Comments

Fetch paginated comments for an article.

**`GET /news/{article_id}/comments`**

### Query Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `page` | int | No | Page number, default `1` |
| `per_page` | int | No | Comments per page, default `20`, max `100` |

### Example Request

```
GET https://vanijyaa-backend.onrender.com/news/3f8a2c1d-9e74-4b1a-8d3f-2c1d9e744b1a/comments?page=1&per_page=20
```

### Response `200 OK`

```json
{
  "success": true,
  "message": "Comments fetched",
  "data": [
    {
      "id": "a1b2c3d4-...",
      "user_id": "uuid-of-commenter",
      "comment_text": "Prices in Punjab will rise this week.",
      "created_at": "2026-04-18T10:15:00"
    }
  ]
}
```

> Comments are returned newest first.

---

## 10. Get Taste Profile

Returns the user's cluster taste weights — shows what type of news they engage with most. Auto-seeds defaults on first call if no data exists.

**`GET /news/my/taste`**

### Query Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `user_id` | UUID | Yes | Acting user's UUID |

### Example Request

```
GET https://vanijyaa-backend.onrender.com/news/my/taste?user_id=<uuid>
```

### Response `200 OK`

```json
{
  "success": true,
  "message": "Taste profile fetched",
  "data": {
    "user_id": "<uuid>",
    "clusters": [
      {
        "cluster_id": 8,
        "cluster_name": "Price Volatility & Sentiment",
        "taste_weight": 0.9,
        "interaction_count": 0,
        "avg_dwell_time": 0.0,
        "is_seeded": true
      },
      {
        "cluster_id": 7,
        "cluster_name": "Market Participation & Deal Flow",
        "taste_weight": 0.7,
        "interaction_count": 3,
        "avg_dwell_time": 38.0,
        "is_seeded": false
      }
    ]
  }
}
```

| Field | Description |
|---|---|
| `taste_weight` | 0.0–1.0, higher = user engages more with this cluster |
| `interaction_count` | Number of engagement events logged for this cluster |
| `avg_dwell_time` | Average seconds the user spends on articles in this cluster |
| `is_seeded` | `true` if this was set from role defaults, `false` if learned from real engagement |

### Errors

| Code | Reason |
|---|---|
| `404` | Profile not found for this user |

---

## 11. Get Engagement History

Returns the user's past interactions with news articles, newest first.

**`GET /news/my/history`**

### Query Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `user_id` | UUID | Yes | Acting user's UUID |
| `action_type` | string | No | Filter by action — `view` / `click` / `dwell` / `like` / `save` / `comment` / `share_out` |
| `page` | int | No | Page number, default `1` |
| `per_page` | int | No | Results per page, default `20`, max `100` |

### Example Request

```
GET https://vanijyaa-backend.onrender.com/news/my/history?user_id=<uuid>&action_type=like&per_page=10
```

### Response `200 OK`

```json
{
  "success": true,
  "message": "Engagement history fetched",
  "data": [
    {
      "id": "a1b2c3d4-...",
      "article_id": "3f8a2c1d-...",
      "action_type": "dwell",
      "segment_id": "trader:wheat:punjab",
      "dwell_time_s": 45,
      "created_at": "2026-04-18T10:00:00"
    }
  ]
}
```

---

## 13. Error Reference

All errors follow this format:

```json
{
  "detail": "Error message here"
}
```

| HTTP Code | Meaning |
|---|---|
| `400` | Bad request — invalid `action_type` or missing required field |
| `404` | Resource not found — article or profile does not exist |
| `422` | Validation error — field too long, wrong type, etc. |
| `500` | Internal server error |

---

## Frontend Quick Reference

### Displaying the feed

```
GET /news/feed?user_id={user_id}&scope=national
```
- Render 5 sections in order: `right_now` → `for_you_today` → `trending` → `worth_knowing` → `government`
- Each article already has `liked`, `saved`, `like_count`, `comment_count`, `share_count`
- Show `trader_impact` / `broker_impact` / `exporter_impact` based on the logged-in user's role

### Tracking engagement (call silently in background)

```
POST /news/{article_id}/engage?user_id={user_id}
Body: { "action_type": "view" }                         ← when article enters viewport
Body: { "action_type": "dwell", "dwell_time_s": 42 }   ← when user leaves article screen
Body: { "action_type": "click" }                        ← when user taps to open full article
```

### Like / Save / Share buttons

```
POST /news/{article_id}/like?user_id={user_id}    → toggle, read back liked + like_count
POST /news/{article_id}/save?user_id={user_id}    → toggle, read back saved
POST /news/{article_id}/share?user_id={user_id}   → increment, read back share_count
```

### Opening article detail

```
GET /news/{article_id}?user_id={user_id}
```
Then call engage with `action_type: click` right after.

### Posting a comment

```
POST /news/{article_id}/comment?user_id={user_id}
Body: { "text": "..." }
```
Then refresh comments with `GET /news/{article_id}/comments`.
