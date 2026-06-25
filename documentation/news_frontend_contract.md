# News Module — Frontend Contract

Complete API contract for the news tab. Covers every endpoint, exact request/response shapes, pagination, interaction flows, and error codes.

---

## Authentication

All endpoints require a JWT bearer token.

```
Authorization: Bearer <access_token>
```

The token encodes `profile_id` (used for personalisation, liked/saved state) and `user_id` (used for in-app share WebSocket events).

---

## Response Envelope

All responses use the shared `ok()` wrapper:

```json
{
  "success": true,
  "message": "...",
  "data": { ... }
}
```

On error:
```json
{
  "success": false,
  "message": "...",
  "data": null
}
```

The `data` field contains the payload described in each section below.

---

## Common Types

### `NewsCard`

Returned by all feed list endpoints.

```ts
{
  article_id: string            // UUID
  title: string
  image_url: string | null
  source_name: string | null
  time_on_platform: string      // "3h" | "Yesterday" | "5 days ago"
  platform_arrived_at: string   // ISO 8601 datetime (UTC)
  summary_bullets: string[] | null   // up to 3 bullet points
  primary_factor: string | null // taxonomy slug — see below
  geo_category: "global" | "domestic" | null
  is_government: boolean
  impact_direction: "positive" | "neutral" | "negative" | null
  impact_score: number | null   // 0–10
  like_count: number
  share_count: number
  is_liked: boolean             // true if current user has liked
  is_saved: boolean             // true if current user has saved
}
```

### `NewsCardDetail`

Extends `NewsCard` with full article content. Returned by the detail endpoint.

```ts
{
  ...NewsCard,
  description: string | null
  article_url: string           // external article URL (open in WebView)
  source_url: string | null
  published_at: string          // ISO 8601 (when the original publisher published)
  impact_explanation: string | null   // one sentence on market impact
  impact_factor: string | null        // short label e.g. "Export ban"
  factor_scores: Array<{ factor: string, score: number }> | null
  view_count: number | null
  save_count: number | null
}
```

### `primary_factor` Values

| Slug | Display Name |
|------|-------------|
| `policy_regulation` | Policy & Regulation |
| `geopolitical_macro` | Geopolitical & Macro |
| `supply_disruptions` | Supply Disruptions |
| `financial_mechanics` | Financial & Market |
| `structural_shifts` | Structural Shifts |
| `long_term_demand` | Long-term Demand |
| `deal_flow` | Deal Flow |
| `price_volatility` | Price Volatility |
| `local_operational` | Local Operational |
| `indirect_general` | General |

### Pagination

All list feeds use cursor-based pagination. The cursor is the `article_id` (UUID string) of the last article in the current page.

```ts
{
  articles: NewsCard[]
  next_cursor: string | null    // null = no more pages
}
```

- First request: omit `cursor_article_id`
- Subsequent requests: pass `cursor_article_id = data.next_cursor` from the previous response
- When `next_cursor` is `null`, the feed is exhausted

---

## Feed Endpoints

### 1. `GET /news/feed` — Recommended Feed (Landing Page)

Personalised feed for the news tab landing page. Articles are scored using the user's role, declared commodities, and business state. Articles older than 48 hours are excluded.

**Query Parameters**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 20 | Items per page (max 50) |
| `cursor_article_id` | string (UUID) | — | Cursor from previous page |

**Response `data`**

```ts
{
  articles: NewsCard[]
  next_cursor: string | null
}
```

**Notes**
- Pool refreshes every 30 min as new articles are ingested and enriched
- Score order is stable within a session page but may shift across sessions as the pool changes
- If pool in the last 12h has fewer than 30 articles, the window expands to 24h, then 48h

---

### 2. `GET /news/trending` — Trending Feed

Platform-wide trending articles ordered by engagement velocity (likes, saves, shares, dwell time) over the last 6 hours. Refreshed every 5 minutes.

**Query Parameters**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 20 | Items per page (max 50) |
| `cursor_article_id` | string (UUID) | — | Cursor from previous page |

**Response `data`**

```ts
{
  articles: NewsCard[]
  next_cursor: string | null
}
```

**Notes**
- Not personalised — same order for all users
- Velocity recomputed every 5 min; cursor position may shift slightly between pages if trending list changes

---

### 3. `GET /news/feed/saved` — Saved Articles

Articles the current user has saved, ordered by most-recently saved first.

**Query Parameters**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 20 | Items per page (max 50) |
| `cursor_article_id` | string (UUID) | — | Cursor from previous page |

**Response `data`**

```ts
{
  articles: NewsCard[]
  next_cursor: string | null
}
```

---

### 4. `GET /news/feed/global` — Global News

Articles classified as global (cross-border / international) events. Ordered by recency. No personalisation.

**Query Parameters**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 20 | Items per page (max 50) |
| `cursor_article_id` | string (UUID) | — | Cursor from previous page |

**Response `data`**

```ts
{
  articles: NewsCard[]
  next_cursor: string | null
}
```

---

### 5. `GET /news/feed/domestic` — Domestic News

Articles classified as domestic (India home market). Ordered by recency. No personalisation.

**Query Parameters**

Same as `/news/feed/global`.

**Response `data`**

```ts
{
  articles: NewsCard[]
  next_cursor: string | null
}
```

---

### 6. `GET /news/feed/government` — Government / Policy News

Articles where a government body, ministry, regulator, central bank, or parliament is the main actor. Independent of geo_category — can be global or domestic. Ordered by recency.

**Query Parameters**

Same as `/news/feed/global`.

**Response `data`**

```ts
{
  articles: NewsCard[]
  next_cursor: string | null
}
```

---

### 7. `GET /news/articles/{article_id}` — Article Detail

Full detail card for a single article.

**Path Parameters**

| Param | Type | Description |
|-------|------|-------------|
| `article_id` | UUID | Article identifier |

**Response `data`**

```ts
NewsCardDetail
```

**Error**

| Code | Condition |
|------|-----------|
| 404 | Article not found or inactive |

---

## Interaction Endpoints

### 8. `POST /news/interactions/batch` — Submit Client Events

Submit a batch of client-side engagement events. Call this periodically (e.g., when the user leaves a screen or on a 30s flush timer). Events older than 2 hours are silently dropped.

**Request Body**

```ts
{
  events: Array<{
    article_id: string        // UUID
    event_type: "impression" | "dwell" | "open_article" | "share_tap"
    value_ms?: number         // required for "dwell" — duration in milliseconds
    occurred_at: string       // ISO 8601 datetime (UTC) when the event happened
  }>
}
```

**Event Types**

| Type | When to fire | `value_ms` |
|------|-------------|-----------|
| `impression` | Article card becomes visible in feed (≥50% visible) | Not used |
| `dwell` | User stopped scrolling on a card | Duration visible in ms (required) |
| `open_article` | User tapped a card to open detail view | Not used |
| `share_tap` | User tapped the share button (before choosing a destination) | Not used |

**Batch limits**
- Min: 1 event
- Max: 200 events per batch

**Response `data`**

```ts
{
  accepted: number
  dropped: number
}
```

**Notes**
- Articles not found in the DB are silently dropped (counted in `dropped`)
- Duplicate impressions within a session are accepted — the server deduplicates `open_article` events into `revisit` signals

---

### 9. `POST /news/interactions/like/{article_id}` — Toggle Like

Toggles like on/off. Calling it twice returns to the original state.

**Path Parameters**

| Param | Type | Description |
|-------|------|-------------|
| `article_id` | UUID | Article to like/unlike |

**Response `data`**

```ts
{
  article_id: string    // UUID
  is_liked: boolean     // new state after toggle
}
```

**Notes**
- Update the `is_liked` and `like_count` on the card optimistically before the response arrives
- On error, revert optimistic update

---

### 10. `POST /news/interactions/save/{article_id}` — Toggle Save

Toggles save on/off. When saved, the article appears in `GET /news/feed/saved`.

**Path Parameters**

| Param | Type | Description |
|-------|------|-------------|
| `article_id` | UUID | Article to save/unsave |

**Response `data`**

```ts
{
  article_id: string    // UUID
  is_saved: boolean     // new state after toggle
}
```

---

### 11. `POST /news/interactions/share/{article_id}` — External Share

Records an external share (WhatsApp, copy link, etc.). Does NOT send any in-app message. Call this when the user shares via any channel outside the app.

**Path Parameters**

| Param | Type | Description |
|-------|------|-------------|
| `article_id` | UUID | Article being shared |

**Query Parameters**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `platform` | string | — | Optional — `"whatsapp"`, `"copy"`, `"other"` |

**Response `data`**

```ts
{
  article_id: string
  platform: string | null
}
```

---

### 12. `GET /news/interactions/share-sheet/{article_id}` — Share Recipients

Returns the list of DM conversations and groups the user can forward this article to. Call this when the user taps "Send inside app" to populate the share sheet.

**Path Parameters**

| Param | Type | Description |
|-------|------|-------------|
| `article_id` | UUID | Article being shared |

**Response `data`**

Same shape as `GET /connections/share-recipients` (DM connections + joined groups).

```ts
{
  dms: Array<{
    conversation_id: string   // UUID — pass to /send
    user_id: string
    name: string
    avatar_url: string | null
  }>
  groups: Array<{
    group_id: string          // UUID — pass to /send
    name: string
    avatar_url: string | null
    member_count: number
  }>
}
```

---

### 13. `POST /news/interactions/send/{article_id}` — In-App Share

Delivers the article as a chat message to selected DMs and/or groups. Increments `share_count` once regardless of recipient count. Triggers WebSocket events to recipients.

**Path Parameters**

| Param | Type | Description |
|-------|------|-------------|
| `article_id` | UUID | Article to send |

**Request Body**

```ts
{
  dm_conversation_ids: string[]   // UUID array — DM conversations to send to
  group_ids: string[]             // UUID array — groups to send to
  caption?: string                // optional message (max 4000 chars)
}
```

At least one of `dm_conversation_ids` or `group_ids` must be non-empty.

**Response `data`**

```ts
{
  share_count: number     // updated total share count for the article
  delivered_to: number    // total recipients the message was delivered to
}
```

**WebSocket Events Emitted to Recipients**

DM recipient receives:
```json
{ "event": "new_message", "data": { ...message } }
```

Group members receive:
```json
{ "event": "new_group_message", "data": { ...message } }
```

---

## Complete Flows

### Flow 1: Opening the News Tab

```
1. GET /news/feed
   → Render recommended articles (landing page)
   → Store next_cursor for infinite scroll

2. As user scrolls:
   → Batch impression + dwell events locally

3. When user leaves the screen (or every 30s):
   → POST /news/interactions/batch  (flush all buffered events)
```

---

### Flow 2: Switching Tabs (Global / Domestic / Government / Trending)

```
Each tab is a separate feed — call its endpoint independently.

GET /news/feed/global      → global tab
GET /news/feed/domestic    → domestic tab
GET /news/feed/government  → government/policy tab
GET /news/trending         → trending tab

Each has its own cursor state. Tabs do NOT share cursor.
Flush buffered events (POST /batch) when switching away.
```

---

### Flow 3: Opening an Article

```
1. Fire "open_article" event into local batch

2. GET /news/articles/{article_id}
   → Render full detail view (article_url in WebView, bullets, impact)

3. If user scrolls / reads:
   → Track dwell time locally

4. On close / back:
   → POST /news/interactions/batch  with dwell event for this article
```

---

### Flow 4: Like

```
1. User taps like icon
   → Optimistically toggle is_liked on card, ±1 like_count

2. POST /news/interactions/like/{article_id}
   → On success: confirm new state (is_liked in response)
   → On error:  revert optimistic update
```

---

### Flow 5: Save

```
1. User taps bookmark icon
   → Optimistically toggle is_saved on card

2. POST /news/interactions/save/{article_id}
   → On success: confirm new state (is_saved in response)
   → On error:  revert optimistic update

Saved articles appear in GET /news/feed/saved.
```

---

### Flow 6: External Share (WhatsApp / Copy Link)

```
1. User taps share → chooses "WhatsApp" or "Copy link"

2. Fire "share_tap" event into local batch (for taste signals)

3. POST /news/interactions/share/{article_id}?platform=whatsapp
   → No response payload needed; fire-and-forget

4. Perform the actual system share (open WhatsApp, copy to clipboard, etc.)
```

---

### Flow 7: In-App Share (Send to DM or Group)

```
1. User taps "Send inside app"

2. GET /news/interactions/share-sheet/{article_id}
   → Render contact picker (DMs + groups)

3. User selects recipients + optional caption

4. POST /news/interactions/send/{article_id}
   Body: { dm_conversation_ids: [...], group_ids: [...], caption: "..." }
   → Recipients receive WebSocket "new_message" / "new_group_message" event
   → Response: { share_count, delivered_to }

5. Update share_count on article card
```

---

### Flow 8: Saved Feed

```
1. GET /news/feed/saved
   → Render user's saved articles

2. To unsave from within saved feed:
   POST /news/interactions/save/{article_id}   (toggle — removes the save)
   → Remove article from list locally
```

---

### Flow 9: Infinite Scroll (All Feeds)

```
On every feed:

1. Initial load: GET /news/<feed>?limit=20
   → Render articles[0..19]
   → Store next_cursor

2. User reaches ~80% scroll depth:
   → GET /news/<feed>?limit=20&cursor_article_id=<next_cursor>
   → Append to list
   → Update next_cursor

3. When next_cursor === null:
   → Show "You're all caught up" / stop fetching
```

---

## Error Reference

| HTTP Code | Meaning |
|-----------|---------|
| 400 | Validation error (e.g., missing `value_ms` on dwell event, empty batch) |
| 401 | Missing or expired JWT |
| 404 | Article not found (detail endpoint) |
| 422 | Request body schema mismatch |
| 500 | Server error |

---

## Timing and Refresh

| Feed | Freshness | When to Refresh |
|------|-----------|-----------------|
| Recommended (`/news/feed`) | ~30 min (new articles ingested every 30 min) | On tab focus |
| Trending (`/news/trending`) | ~5 min (velocity recomputed every 5 min) | On tab focus |
| Global / Domestic / Government | ~30 min | On tab focus |
| Saved | Real-time | After save/unsave actions |

---

## Event Batching Strategy (Recommended)

- Buffer events in memory as the user scrolls
- Flush on any of:
  - User navigates away from news tab
  - User backgrounds the app
  - 30-second timer fires (while on news tab)
  - Batch reaches 50 events
- Cap `value_ms` for dwell at 600,000 (10 min) before sending — server also caps at this value
- `occurred_at` must be the actual client timestamp — events older than 2 hours are dropped server-side
