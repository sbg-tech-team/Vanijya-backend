# Following Feed — Frontend Contract

## What Changed from the Previous Implementation

### API Changes

- **Response shape is no longer a plain array.** The endpoint previously returned `PostCard[]` directly. It now returns an object:
  ```json
  { "posts": [...], "all_caught_up": false, "next_cursor": 412 }
  ```
  Any code doing `response.map(...)` or treating the response as an array will break — change to `response.posts.map(...)`.

- **`?offset` query param is removed.** Replaced by `?cursor` (an integer post ID). Sending `?offset=20` will be silently ignored; only `cursor` drives pagination.

- **New query param `cursor`.** Pass the `next_cursor` value from the previous response. Omit (or send `null`) on the first load. See the pagination flow below.

- **Two new response fields:**
  - `all_caught_up: boolean` — indicates all recent posts have been seen.
  - `next_cursor: integer | null` — the cursor for the next page. `null` means end of feed.

- **`post_card.image_urls` is now an array**, not a single string. Was `image_url: string`, now `image_urls: string[] | null`. Use `image_urls[0]` for the primary image thumbnail.

### Behaviour Changes

- **Feed is now ranked, not chronological.** Posts are scored by commodity match, taste category preference, freshness, and engagement — the most relevant post appears first, not the most recent.

- **Seen posts are excluded.** Posts the viewer has already seen (dwell ≥ 3 seconds, processed by the server scheduler) no longer appear in the feed. This happens on the next load, not within the current scroll session.

- **Cross-feed deduplication is active.** A post seen in the recommendation feed disappears from the following feed on next load, and vice versa. Both feeds share the same `seen_posts` table.

- **Time window expanded from 7 days to 30 days.** Because ranking now handles relevance, older posts from followed accounts surface at the bottom rather than being cut off entirely.

- **Closed deals are shown** (previously no distinction). They appear in the feed but with a 0.5× score penalty so they rank lower than open deals. `deal_details.is_closed: true` signals this to the UI.

- **Interaction events are now expected from this feed too.** The client must fire `impression` and `dwell` events via `POST /posts/interactions/batch` for posts in the following tab — the same endpoint used for the recommendation feed. Without these events, posts will never be marked as seen and will reappear on every load.

- **"All caught up" state is new.** When all posts from the last 3 days from followed accounts have been seen, `all_caught_up: true` is returned. Show a contextual banner rather than a generic empty state.

---

## Endpoint

```
GET /posts/following
Authorization: Bearer <token>
```

### Query Parameters

| Parameter | Type    | Required | Default | Description |
|-----------|---------|----------|---------|-------------|
| `limit`   | integer | No       | 20      | Max posts per page |
| `cursor`  | integer | No       | null    | Last `post_id` from the previous page. Omit or send `null` for the first load. |

---

## Response Shape

```json
{
  "posts": [ PostCard, ... ],
  "all_caught_up": false,
  "next_cursor": 412
}
```

| Field           | Type              | Description |
|-----------------|-------------------|-------------|
| `posts`         | `PostCard[]`      | Ranked list of posts for this page |
| `all_caught_up` | `boolean`         | `true` when all posts from the last 3 days from followed accounts have been seen |
| `next_cursor`   | `integer \| null` | Pass as `?cursor=` in the next request. `null` means no more posts. |

---

## PostCard Schema

```json
{
  "id": 412,
  "profile_id": 7,
  "category_id": 4,
  "commodity_id": 1,
  "title": "Basmati Rice Available — 500 MT",
  "caption": "Grade A Basmati, export quality...",
  "image_urls": ["https://...", "https://..."],
  "source_url": "https://agmarket.nic.in/...",
  "location_name": "Amritsar, Punjab",
  "latitude": 31.634,
  "longitude": 74.872,
  "is_public": true,
  "target_roles": null,
  "allow_comments": true,
  "deal_details": {
    "grain_type": "Basmati",
    "grain_size": "Long",
    "commodity_quantity": 500.0,
    "quantity_unit": "MT",
    "commodity_price": 82000.0,
    "price_type": "negotiable",
    "is_closed": false
  },
  "view_count": 34,
  "like_count": 12,
  "comment_count": 3,
  "share_count": 1,
  "save_count": 5,
  "is_liked": false,
  "is_saved": true,
  "created_at": "2026-06-07T10:22:00Z",
  "time_elapsed": "2 days ago"
}
```

`deal_details` is `null` for non-deal category posts (Market Update, Discussion, Knowledge).

---

## Flow

### 1. First Load (session start)

Call the endpoint with no `cursor`:

```
GET /posts/following?limit=20
```

- The server fetches all posts from followed accounts from the last **30 days**, excluding any posts already in the `seen_posts` table (posts marked seen in a previous session).
- Posts are **ranked** by relevance — not pure chronological. Ranking factors:
  - Taste/category preference (deal posts ranked higher for users who engage with deals)
  - Commodity match (posts matching the viewer's commodities get a 1.3× boost)
  - Freshness (exponential decay — a post from 2 hours ago scores higher than one from 3 days ago)
  - Closed deal penalty (closed deals are shown but scored at 0.5×)
  - Light engagement signal (likes, saves, comments)
- The first 20 (or `limit`) ranked posts are returned.
- Store `next_cursor` from the response. If `null`, there are no more posts.

---

### 2. Infinite Scroll (subsequent pages)

When the user scrolls near the bottom of the list, call:

```
GET /posts/following?limit=20&cursor=412
```

where `412` is the `next_cursor` from the previous response.

- The server re-ranks all currently unseen candidates and finds the position of `cursor` post in that ranked list, then returns the next `limit` posts after it.
- If `next_cursor` in the new response is `null`, there are no more posts — show an end-of-feed indicator.

> **Note:** Because the feed is re-ranked on each call (not a static offset), a post created between two pages may appear at the top on the next session but will not appear mid-scroll in the current session (since its ID won't be before the cursor position yet).

---

### 3. Marking Posts as Seen (interaction events)

The following feed shares the same seen-post mechanism as the recommendation feed. The **client** is responsible for sending interaction events.

**When to fire events:**

| Event        | When to send |
|--------------|-------------|
| `impression` | As soon as a post enters the viewport |
| `dwell`      | When the user has had the post in view for the measured duration (in ms) |

**Endpoint:**

```
POST /posts/interactions/batch
Authorization: Bearer <token>
Content-Type: application/json

{
  "events": [
    {
      "post_id": 412,
      "event_type": "impression",
      "occurred_at": "2026-06-09T08:10:00Z",
      "value_ms": null
    },
    {
      "post_id": 412,
      "event_type": "dwell",
      "occurred_at": "2026-06-09T08:10:08Z",
      "value_ms": 8200
    }
  ]
}
```

- The **same endpoint** is used for both the recommendation feed and the following feed. There is no `feed_source` field needed.
- A dwell event with `value_ms >= 3000` causes the server's scheduler to write the post to `seen_posts`.
- Once a post is in `seen_posts`, it will not appear in either feed on the **next** load (recommendation or following).

---

### 4. Cross-Feed Deduplication

The `seen_posts` table is **shared** between the recommendation feed and the following feed.

Behavior per session:

```
Session start (cold):
  ┌─────────────────────────────────────────┐
  │  Rec Feed     │  Following Feed          │
  │  post 123 ✓  │  post 123 ✓  (both can  │
  │               │              show it)    │
  └─────────────────────────────────────────┘

User sends dwell ≥ 3s on post 123 (from either tab):
  → scheduler writes post 123 to seen_posts

Next API call to either feed:
  ┌─────────────────────────────────────────┐
  │  Rec Feed     │  Following Feed          │
  │  post 123 ✗  │  post 123 ✗  (gone      │
  │               │              from both)  │
  └─────────────────────────────────────────┘
```

> Within the same scroll session, a post already rendered will not disappear. It disappears only on the **next** feed load/refresh.

---

### 5. "All Caught Up" State

`all_caught_up: true` is returned when:
- The viewer follows at least one account that has posted in the last 3 days, AND
- All of those recent posts have already been seen (are in `seen_posts`)

**UI recommendation:** Show a "You're all caught up!" banner at the top (or bottom) of the feed instead of the empty state. Do not hide older posts (30-day window) — the user can still scroll down to see them.

`all_caught_up` is only ever `true` on the **first page** (no cursor). On subsequent pages it will always be `false`.

---

### 6. Empty States

| Condition | `posts` | `all_caught_up` | `next_cursor` | Suggested UI |
|-----------|---------|-----------------|---------------|-------------|
| Not following anyone | `[]` | `false` | `null` | "Follow traders to see their posts here" |
| Following accounts but no posts in 30 days | `[]` | `false` | `null` | "No recent posts from people you follow" |
| All recent (3-day) posts seen, older posts remain | `[...older posts]` | `true` | depends | "You're all caught up!" banner + show older posts below |
| All posts (30-day) seen | `[]` | `true` | `null` | "You're all caught up! Check back later." |

---

### 7. Full Scroll Flow (summary)

```
App opens → GET /posts/following (no cursor)
  ↓
Render 20 posts, store next_cursor
  ↓
User scrolls → send impression events for visible posts
  ↓
User dwells 3s+ on post → send dwell event
  ↓
User reaches bottom → GET /posts/following?cursor=<next_cursor>
  ↓
Append next 20 posts, update next_cursor
  ↓
next_cursor == null → show end-of-feed
  ↓
User pulls-to-refresh → GET /posts/following (no cursor, fresh first load)
  → seen posts from previous session are now excluded
```

---

## Category IDs Reference

| `category_id` | Name |
|---------------|------|
| 1 | Market Update |
| 2 | Knowledge |
| 3 | Discussion |
| 4 | Deal / Requirement |

## Commodity IDs Reference

| `commodity_id` | Name |
|----------------|------|
| 1 | Rice |
| 2 | Cotton |
| 3 | Sugar |
