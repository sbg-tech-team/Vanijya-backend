# Home Feed API

> Frontend-facing contract for the **current** feed endpoints.
> For the design/roadmap (taste layers, GST/GT, phases) see
> `app/modules/feed/ARCHITECTURE.md`.

Base prefix: `/feed` · Auth: **Bearer access token** required on every endpoint.

The feed is a single **mixed stream** of four item types — `post`, `news`, `group`,
`connection`. Item ranking is delegated to each module's recommender; the feed
interleaves them (weighted-random, max 3 of a type in a row) and prepends
breaking-news on first load.

---

## Response envelope

Every endpoint returns:

```jsonc
{
  "success": true,
  "message": "Feed fetched successfully",
  "data": { ... }            // endpoint-specific payload
}
```

---

## GET /feed/home

Returns one page of the mixed feed.

### Request

| Param | In | Type | Required | Notes |
|---|---|---|---|---|
| `Authorization` | header | `Bearer <token>` | ✅ | `user_id` + `profile_id` read from JWT claims |
| `cursor` | query | JSON string | ❌ | Omit on first call. Pass the `cursor` from the previous response to page. |

- **First call (no cursor):** breaking-news **priority pins** are resolved and prepended.
- **Subsequent calls:** pass back `cursor`. Current cursor is just `{"page_num": n}`.

```
GET /feed/home
GET /feed/home?cursor={"page_num":2}
# URL-encoded: /feed/home?cursor=%7B%22page_num%22%3A2%7D
```

Invalid cursor JSON → `400 { detail: "Invalid cursor format" }`.

### Response — `data`

```jsonc
{
  "items": [ FeedItem, ... ],            // the mixed page (≤ 20)
  "cursor": { "page_num": 2 },           // pass to next GET
  "has_more": true,                      // false when all source pools are empty
  "weights_used": {                      // debug: type-mix ratio used this page
    "post": 0.45, "news": 0.25, "group": 0.15, "connection": 0.15
  }
}
```

### FeedItem — common shape

```jsonc
{
  "item_type": "post",                   // "post" | "news" | "group" | "connection"
  "item_id": "42",                       // string; post=int-as-str, news/group=uuid, connection=user uuid
  "is_priority": false,                  // true only for breaking-news pins (first page)
  "content_type_label": "post",          // "post" | "news" | "breaking_news" | "group_suggestion" | "connection"
  "data": { ... }                        // type-specific, see below
}
```

> `data` is passed through **verbatim** from each source recommender. The shapes below
> reflect what those modules return today; treat unknown/extra fields as additive.

---

### `data` for `item_type: "post"`

Source: `post_recommendation_module.get_recommended_posts` → `FeedPostCard`.

```jsonc
{
  "id": 42,
  "profile_id": 7,
  "category_id": 2,
  "commodity_id": 5,
  "title": "...",
  "caption": "...",
  "image_urls": ["https://..."],
  "source_url": null,
  "allow_comments": true,
  "deal_details": null,                  // present for deal_req posts
  "location_name": null,
  "location_city": null,
  "location_state": null,

  "like_count": 12,
  "comment_count": 3,
  "is_liked": false,                     // viewer state, pre-computed
  "is_saved": false,
  "time_elapsed": "2h ago",              // computed; created_at is NOT returned

  "author_name": "...",
  "author_role": "Trader",               // "Trader" | "Broker" | "Exporter"
  "author_user_id": "<uuid>",
  "author_company": null,
  "author_avatar_url": null,
  "is_following": false,                 // viewer follows author?
  "is_user_verified": false,
  "is_business_verified": false
}
```

### `data` for `item_type: "news"`

Source: `news.get_news_feed` → `ArticleOut`.
`content_type_label` is `"breaking_news"` for first-page pins (from the `right_now`
section), `"news"` for the regular pool (from `for_you_today`).

```jsonc
{
  "id": "<uuid>",
  "title": "...",
  "summary": "...",
  "url": "https://...",
  "image_url": "https://...",
  "published_at": "2026-06-18T08:00:00+00:00",
  "cluster_id": 12,
  "severity": 8.5,
  "commodities": ["WHEAT"],
  "regions": ["IN-MH"],
  "scope": "national",
  "direction_tags": [],
  "horizon": "short",
  "source_name": "...",
  "source_credibility": 0.8,
  "source_category": "government",
  "trader_impact": "...",
  "broker_impact": "...",
  "exporter_impact": "...",
  "liked": false,
  "saved": false,
  "like_count": 0
}
```

### `data` for `item_type: "group"`

Source: `groups.get_group_suggestions` → `GroupOut` + match fields.
These are **"groups you might join"** suggestions, not group-post activity.

```jsonc
{
  "id": "<uuid>",
  "name": "...",
  "description": "...",
  "group_rules": null,
  "image_url": "https://...",
  "commodity": ["wheat"],
  "target_roles": ["trader"],
  "region_market": null,
  "region_lat": null,
  "region_lon": null,
  "category": null,
  "accessibility": "public",
  "posting_perm": "all_members",
  "chat_perm": "all_members",
  "member_count": 24,
  "created_by": "<uuid>",
  "created_at": "2026-05-01T10:00:00+00:00",
  "is_member": false,
  "member_role": null,

  "match_score": 0.81,                   // added by feed
  "match_reasons": ["Same commodity: wheat", "..."]   // added by feed
}
```

### `data` for `item_type: "connection"`

Source: `connections.get_recommendations` → one entry of `results`.
`item_id` is the candidate's **user_id (uuid)**.

```jsonc
{
  "user_id": "<uuid>",
  "name": "...",
  "avatar_url": null,
  "role": "trader",
  "commodity": ["wheat", "cotton"],
  "is_user_verified": false,
  "is_business_verified": false,
  "quantity_min": 100,
  "quantity_max": 500,
  "business_name": "...",
  "city": "...",
  "state": "...",
  "msg_req_status": null,                // "pending" | "accepted" | "declined" | null
  "follow_status": false,
  "similarity": 0.93                     // cosine, 0..1
}
```

---

## POST /feed/engagement

Submit a batch of engagement signals from the client.

> **Current behaviour: acknowledge-only.** Signals are accepted and counted but **not
> yet forwarded** to the source modules or used for taste. Forwarding + taste land in
> later phases (see ARCHITECTURE.md §9). Safe to start sending now.

### Request — body

```jsonc
{
  "signals": [
    {
      "item_id": "42",
      "item_type": "post",               // "post" | "news" | "group" | "connection"
      "action": "dwell",                 // see actions below
      "dwell_ms": 5200                   // required for dwell/strong_dwell/skip
    }
  ],
  "cursor": { "page_num": 2 }            // optional
}
```

**Actions:** `dwell`, `strong_dwell`, `skip`, `like`, `save`, `share`, `comment`,
`connection_accept`, `connection_dismiss`.

### Response

`201` ·

```jsonc
{
  "success": true,
  "message": "Engagement recorded",
  "data": { "acknowledged": true, "signals_processed": 1 }
}
```

---

## Current limitations & notes

- **Engagement is ack-only** — no taste/forwarding yet.
- **Type-mix is static** (`post .45 / news .25 / group .15 / connection .15`); not yet
  personalized.
- **Breaking-news pins** appear on the **first page only** (no cursor).
- **Pagination is shallow:** the post & news recommenders are not page-based, so
  `page_num` mainly advances connection/group suggestions; post/news novelty across
  pages relies on each module's own seen-set. Some repetition is expected for now.
- **Graceful degradation:** if any one source recommender errors (or its dependency
  like Redis is unreachable), that item type is silently omitted and the rest of the
  feed still returns.
- **Auth:** the JWT carries both `user_id` and `profile_id` (no DB lookup per request).
```
