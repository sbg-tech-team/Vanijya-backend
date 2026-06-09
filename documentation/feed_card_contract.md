# Feed Card — Frontend Contract

Applies to: **Recommendation Feed**, **Following Feed**, **Home Feed (future)**, **View Profile Feed (future)**.

---

## What Changed

- **Single unified card schema** (`FeedPostCard`) is now returned by all feed endpoints. Previously recommendation and following feeds had different shapes.
- **Author info is now included** directly in every card — no separate profile lookup needed to render a card.
- **`is_following`** is now a field on every card — the Follow button state can be set from the feed response.
- **`created_at` is removed** from the response. Use `time_elapsed` instead.
- **`is_public`, `target_roles`** removed — not relevant to the viewer.
- **`latitude`, `longitude`** removed — use `location_name`, `location_city`, `location_state`.
- **`view_count`, `share_count`, `save_count`** removed from the card.
- **`comment_preview_author`, `comment_preview_text`** removed.
- **`location_city` and `location_state`** added (from the author's business profile, optional).

---

## FeedPostCard Schema

```json
{
  "id": 412,
  "profile_id": 7,
  "category_id": 4,
  "commodity_id": 1,
  "title": "Basmati Rice Available — 500 MT",
  "caption": "Grade A Basmati, export quality. Immediate dispatch available.",
  "image_urls": ["https://...", "https://..."],
  "source_url": "https://agmarket.nic.in/...",
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
  "location_name": "Amritsar Mandi",
  "location_city": "Amritsar",
  "location_state": "Punjab",
  "like_count": 12,
  "comment_count": 3,
  "is_liked": false,
  "is_saved": true,
  "time_elapsed": "2 days ago",
  "author_name": "Harpreet Singh",
  "author_role": "Trader",
  "author_user_id": "a1b2c3d4-...",
  "author_company": "Singh Agro Exports",
  "author_avatar_url": "https://...",
  "is_following": true,
  "is_user_verified": true,
  "is_business_verified": false
}
```

---

## Field Reference

### Post Fields

| Field | Type | Notes |
|-------|------|-------|
| `id` | `integer` | Post ID |
| `profile_id` | `integer` | Author's profile ID |
| `category_id` | `integer` | See category table below |
| `commodity_id` | `integer` | See commodity table below |
| `title` | `string` | |
| `caption` | `string` | Full post body text |
| `image_urls` | `string[] \| null` | Up to 5 images. Use `[0]` for thumbnail. |
| `source_url` | `string \| null` | External link attached to the post |
| `allow_comments` | `boolean` | Whether comments are enabled |
| `deal_details` | `DealDetails \| null` | Only present when `category_id == 4` |
| `location_name` | `string \| null` | Post's own location label (e.g. "Amritsar Mandi") |
| `location_city` | `string \| null` | Author's business city |
| `location_state` | `string \| null` | Author's business state |
| `like_count` | `integer` | |
| `comment_count` | `integer` | |
| `is_liked` | `boolean` | Whether the current viewer has liked this post |
| `is_saved` | `boolean` | Whether the current viewer has saved this post |
| `time_elapsed` | `string` | Human-readable age: "just now", "3 minutes ago", "2 days ago", etc. |

### Author Fields

| Field | Type | Notes |
|-------|------|-------|
| `author_name` | `string` | Display name |
| `author_role` | `string` | `"Trader"` \| `"Broker"` \| `"Exporter"` |
| `author_user_id` | `string` | UUID — use for Follow/Unfollow API calls |
| `author_company` | `string \| null` | Business/company name |
| `author_avatar_url` | `string \| null` | Profile picture URL |
| `is_following` | `boolean` | Whether the current viewer follows this author |
| `is_user_verified` | `boolean` | |
| `is_business_verified` | `boolean` | |

### DealDetails Schema

| Field | Type | Notes |
|-------|------|-------|
| `grain_type` | `string` | e.g. "Basmati", "Non-Basmati" |
| `grain_size` | `string` | e.g. "Long", "Medium", "Short" |
| `commodity_quantity` | `float` | |
| `quantity_unit` | `string` | `"MT"` or `"quintal"` |
| `commodity_price` | `float` | Price in INR |
| `price_type` | `string` | `"fixed"` or `"negotiable"` |
| `is_closed` | `boolean` | `true` = deal is no longer active; show a "Closed" badge |

---

## Recommendation Feed Endpoint

```
GET /posts/recommended
Authorization: Bearer <token>
```

**Response:**

```json
[FeedPostCard, FeedPostCard, ...]
```

Plain array of `FeedPostCard`. No cursor — the engine always returns a fresh ranked set (up to 25 posts). Call again to refresh.

---

## Following Feed Endpoint

```
GET /posts/following?limit=20&cursor=<post_id>
Authorization: Bearer <token>
```

**Response:**

```json
{
  "posts": [FeedPostCard, FeedPostCard, ...],
  "all_caught_up": false,
  "next_cursor": 412
}
```

| Field | Type | Notes |
|-------|------|-------|
| `posts` | `FeedPostCard[]` | Ranked page of posts |
| `all_caught_up` | `boolean` | All posts from the last 3 days from followed accounts have been seen |
| `next_cursor` | `integer \| null` | Pass as `?cursor=` on next page. `null` = end of feed. |

See [following_feed_contract.md](following_feed_contract.md) for the full scroll flow and interaction event spec.

---

## Location Display Logic

Three optional location fields are provided. Suggested display priority:

1. If `location_name` is set — show it (it's a post-specific label like "Amritsar Mandi")
2. Else if `location_city` or `location_state` are set — show `"City, State"` (author's business location)
3. Else — show nothing

```js
function displayLocation(card) {
  if (card.location_name) return card.location_name;
  const parts = [card.location_city, card.location_state].filter(Boolean);
  return parts.length ? parts.join(", ") : null;
}
```

---

## Follow Button Logic

Use `is_following` from the card to set the initial button state. When the user taps Follow/Unfollow:

1. Optimistically toggle the button state in UI
2. Call `POST /connections/follow` or `DELETE /connections/unfollow` with `{ "following_user_id": card.author_user_id }`
3. On error, revert the button

Do **not** re-fetch the feed to update follow state — update it locally.

---

## Closed Deal Badge

When `deal_details.is_closed == true`:
- Show a "Closed" or "Deal Closed" badge on the card
- The card still appears in the feed (ranked with a 0.5× penalty but not hidden)
- Disable any "Contact Seller" / "Enquire" CTA on closed deals

---

## Category IDs

| `category_id` | Name |
|---------------|------|
| 1 | Market Update |
| 2 | Knowledge |
| 3 | Discussion |
| 4 | Deal / Requirement |

## Commodity IDs

| `commodity_id` | Name |
|----------------|------|
| 1 | Rice |
| 2 | Cotton |
| 3 | Sugar |
