# News Share — Frontend Contract

## Flow Overview

```
User taps "Share" on an article
        │
        ▼
1. GET /news/interactions/share-sheet/{article_id}
        │  → renders the share-sheet picker (DMs + groups)
        │
User selects recipients + optionally types a caption
        │
        ▼
2. POST /news/interactions/send/{article_id}
        │  → delivers article as chat message to each recipient
        │  → WebSocket event fires to each recipient
        │
        ▼
   Show "Sent to N" confirmation

─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
Separate path — external share (WhatsApp, copy link, etc.):

3. POST /news/interactions/share/{article_id}?platform=whatsapp
        │  → telemetry only, no chat delivery
```

---

## 1. Get Share Sheet

**`GET /news/interactions/share-sheet/{article_id}`**

Auth: Bearer token required

Path param: `article_id` — UUID of the article being shared

**Response `200`:**
```json
{
  "status": "success",
  "message": "Share recipients fetched",
  "data": {
    "dms": [
      {
        "conversation_id": "uuid",
        "user": {
          "user_id": "uuid",
          "profile_id": 12,
          "name": "Ravi Mehta",
          "avatar_url": "https://...",
          "role": "Trader",
          "is_user_verified": true,
          "is_business_verified": false,
          "is_online": true
        }
      }
    ],
    "groups": [
      {
        "group_id": "uuid",
        "name": "Cotton Traders Mumbai",
        "avatar_url": "https://...",
        "member_count": 14
      }
    ]
  }
}
```

**Notes:**
- Only returns DM conversations with status `ACTIVE` (accepted message requests)
- Only returns groups where the user is a member and not frozen
- `article_id` in the path is accepted but not used to filter — same list is returned regardless; it exists for parity with the post share sheet pattern

---

## 2. Send (In-App Delivery)

**`POST /news/interactions/send/{article_id}`**

Auth: Bearer token required

Path param: `article_id` — UUID of the article being shared

**Request body:**
```json
{
  "dm_conversation_ids": ["uuid", "uuid"],
  "group_ids": ["uuid"],
  "caption": "Check this out"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `dm_conversation_ids` | `UUID[]` | at least one of the two | conversation IDs from share-sheet |
| `group_ids` | `UUID[]` | at least one of the two | group IDs from share-sheet |
| `caption` | `string \| null` | no | max 4000 chars |

Validation: at least one of `dm_conversation_ids` or `group_ids` must be non-empty, else `422`.

**Response `200`:**
```json
{
  "share_count": 47,
  "delivered_to": 3
}
```

| Field | Meaning |
|---|---|
| `share_count` | Total lifetime share count on this article (all users) |
| `delivered_to` | Number of DMs + groups this send actually reached |

**Notes:**
- `delivered_to` may be less than the total recipients passed — permission checks run per-recipient and silently skip failures (e.g. if a group froze the user after the share-sheet was fetched)
- `share_count` is incremented **once** per call regardless of `delivered_to`

**Error responses:**
```json
{ "detail": "Article <uuid> not found." }   // 404 — article_id doesn't exist
{ "detail": [...] }                          // 422 — no recipients, caption too long, etc.
```

---

## 3. External / Record Share (Telemetry Only)

**`POST /news/interactions/share/{article_id}`**

Auth: Bearer token required

Query param: `platform` (optional) — `whatsapp`, `copy`, `twitter`, etc.

No request body.

**Response `200`:**
```json
{
  "status": "success",
  "data": {
    "article_id": "uuid",
    "platform": "whatsapp"
  }
}
```

Use this when the user shares externally (copies link, shares to WhatsApp). It increments `share_count` and records a taste signal — no chat message is created.

---

## 4. Generic Share Recipients (Optional)

**`GET /connections/share-recipients`**

Auth: Bearer token required

Same response shape as endpoint 1. Use this to pre-fetch the share-sheet before the user taps share (e.g. on long-press), since it doesn't require an `article_id`.

---

## WebSocket Events (Recipient Side)

When `POST /send` delivers successfully, each recipient gets a push over their existing WebSocket connection.

**DM recipient** — event: `new_message`
```json
{
  "id": "uuid",
  "context_id": "conversation_uuid",
  "context_type": "dm",
  "sender": {
    "user_id": "uuid",
    "name": "Aadya Pande",
    "avatar_url": "https://..."
  },
  "message_type": "news_article",
  "body": "Check this out",
  "news_article": {
    "article_id": "uuid",
    "title": "Cotton prices surge 12% on monsoon fears",
    "image_url": "https://...",
    "source_name": "Economic Times",
    "primary_factor": "price_volatility",
    "impact_direction": "bearish",
    "impact_score": 0.74,
    "first_bullet": "MCX futures hit 6-month high as IMD warns of below-normal July rainfall"
  },
  "sent_at": "2026-06-24T10:30:00Z"
}
```

**Group recipient** — event: `new_group_message`, same shape with `context_type: "group"`.

### `news_article` Snap Field Reference

| Field | Source | Nullable |
|---|---|---|
| `article_id` | `news_raw_articles.id` | no |
| `title` | `news_raw_articles.title` | no |
| `image_url` | `news_raw_articles.image_url` | yes |
| `source_name` | `news_raw_articles.source_name` | yes |
| `primary_factor` | `enriched_articles.primary_factor` | yes — null if article not yet enriched |
| `impact_direction` | `enriched_articles.impact_direction` | yes |
| `impact_score` | `enriched_articles.impact_score` | yes |
| `first_bullet` | first item of `enriched_articles.summary_bullets` | yes |

**Render guidance:** always guard on `null` for enrichment fields. Show the article card with title + image even if `primary_factor`, `impact_direction`, and `first_bullet` are all null.

---

## Deep Link (External URL — Separate Flow)

**`GET /share/news/{article_id}`** — no auth needed

Returns a `vanijyaa://news/{uuid}` deep link + share text. Handled by the deeplink module, independent of the share flow above.

```json
{
  "data": {
    "url": "vanijyaa://news/550e8400-e29b-41d4-a716-446655440000",
    "text": "Cotton prices surge 12%...",
    "image_url": "https://..."
  }
}
```

---

## Tapping a Shared News Card (Deep Navigation)

When a recipient taps the news card inside chat, the frontend navigates to the full article screen using the `article_id` from the message payload.

**`GET /news/feed/articles/{article_id}`**

Auth: Bearer token required

Returns the full article detail: title, body, image, source, enrichment (factor breakdown, impact direction/score, summary bullets, relevancy by role), and interaction stats (likes, saves, shares, views).

**Frontend responsibility:**
- Render the compact `news_article` snap as a card bubble inside chat (title + image + first_bullet)
- On tap → navigate to article detail screen → call this endpoint with `article_id`

**Backend responsibility:**
- The `article_id` is always present in the `news_article` snap on the message
- The detail endpoint exists and is auth-gated

No additional backend work needed for tap-to-open.

---

## Endpoint Summary

| Endpoint | Auth | Purpose | Creates chat msg |
|---|---|---|---|
| `GET /news/interactions/share-sheet/{id}` | ✅ | Fetch share-sheet picker | No |
| `POST /news/interactions/send/{id}` | ✅ | In-app delivery to DMs/groups | **Yes** |
| `POST /news/interactions/share/{id}` | ✅ | External share telemetry | No |
| `GET /connections/share-recipients` | ✅ | Generic share-sheet (no article context) | No |
| `GET /share/news/{id}` | ❌ | Deep link URL generator | No |

---

## Migration Dependency

Before these endpoints are fully functional, the following Alembic migration must be applied:

```
revision: o6p7q8r9s0t1
adds: messages.article_id (UUID, nullable, FK → news_raw_articles.id SET NULL)
```

Run: `alembic upgrade head`
