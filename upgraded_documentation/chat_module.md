# Chat Module — Developer Guide

A complete reference for direct messaging (DM), group chat, deal cards in chat, Socket.IO real-time events, and the group deal creation endpoint that lives here.

**Base URL:** `https://vanijyaa-backend.onrender.com`

**Interactive docs (Swagger):** `https://vanijyaa-backend.onrender.com/docs`

---

## Table of Contents

1. [Module Overview](#1-module-overview)
2. [How User Identity Works](#2-how-user-identity-works)
3. [Architecture — Two Layers](#3-architecture--two-layers)
4. [Database Schema](#4-database-schema)
5. [File Structure](#5-file-structure)
6. [Socket.IO — Real-Time Connection](#6-socketio--real-time-connection)
7. [REST API Quick Reference](#7-rest-api-quick-reference)
8. [Inbox & Sharing APIs](#8-inbox--sharing-apis)
9. [DM Conversation APIs](#9-dm-conversation-apis)
10. [DM Message APIs](#10-dm-message-apis)
11. [Media Upload & Message Deletion](#11-media-upload--message-deletion)
12. [Personal Deal APIs](#12-personal-deal-apis)
13. [Group Chat APIs](#13-group-chat-apis)
14. [Group Deal APIs (Chat)](#14-group-deal-apis-chat)
15. [Conversation Status Flow](#15-conversation-status-flow)
16. [Message Types](#16-message-types)
17. [Shared Objects](#17-shared-objects)
18. [Error Reference](#18-error-reference)

---

## 1. Module Overview

The chat module handles:

- **Direct Messaging (DM)** — one-to-one conversations. First message creates the conversation in a `requested` state; receiver must accept before both sides can send freely.
- **Group Chat** — real-time messaging scoped to a group. Members send text/media/deal/post cards into the group feed.
- **Personal Deals** — Deal/Requirement cards posted inside a DM. Visible only to the two participants.
- **Group Deals (chat entry point)** — Deal/Requirement cards posted into a group chat. `POST /chat/groups/{group_id}/deals` is the canonical endpoint — it creates the deal, inserts a chat card, and pushes a Socket.IO event to the group room all in one call.
- **Media upload** — images, video, audio, and documents are uploaded **directly from the client to Supabase Storage** via a signed URL minted by the backend. The backend never proxies file bytes — see [Section 11](#11-media-upload--message-deletion).
- **Message deletion** — a sender can soft-delete their own message; the attached media object is removed from the bucket in the background.
- **Real-time push** — Socket.IO rooms (`user:{user_id}`, `group:{group_id}`) push `new_message`, `new_group_message`, `new_group_deal`, `conversation_accepted`, `conversation_declined`, `message_deleted`, and `read` events to connected clients. Clients also emit `typing` / `stop_typing`, which the server relays to the chat peer / group room.

---

## 2. How User Identity Works

All REST endpoints require `Authorization: Bearer <token>`. The acting user's identity is derived exclusively from the JWT — **never** from a path or query parameter.

Socket.IO authentication is done in the `connect` handshake (not via HTTP headers) — see [Section 6](#6-socketio--real-time-connection).

---

## 3. Architecture — Two Layers

```
Flutter client
    │
    ├── REST  →  POST /chat/conversations/{id}/messages  (save + return)
    │                    ↓ background task
    │            emit_to_user(receiver_id, "new_message", payload)
    │
    └── Socket.IO  →  receive "new_message" event in real time
```

REST handles persistence. Socket.IO handles push. They are independent — a client that misses a push can always refetch via REST.

---

## 4. Database Schema

### `conversations`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | Auto-generated |
| `type` | VARCHAR(10) | Always `"dm"` for now |
| `status` | VARCHAR(20) | `requested` → `active` or `blocked` |
| `initiator_id` | UUID FK → users.id SET NULL | The user who sent the first message |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | Bumped on every new message |

### `conversation_members`

| Column | Type | Notes |
|---|---|---|
| `conversation_id` | UUID FK → conversations.id CASCADE | |
| `user_id` | UUID FK → users.id CASCADE | |
| `last_read_at` | TIMESTAMPTZ | Nullable — null means never read |
| `is_muted` | BOOL | Per-user notification mute |
| `joined_at` | TIMESTAMPTZ | |

Composite PK: `(conversation_id, user_id)`. Exactly two rows per DM conversation.

### `messages`

A single polymorphic table for both DM and group messages, distinguished by `context_type`.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | Auto-generated |
| `context_type` | VARCHAR(10) | `"dm"` or `"group"` |
| `context_id` | UUID | DM → `conversation.id`; group → `group.id` |
| `sender_id` | UUID FK → users.id CASCADE | |
| `message_type` | VARCHAR(20) | `text` \| `image` \| `video` \| `document` \| `audio` \| `location` \| `deal` \| `post` |
| `body` | TEXT | Message text — null for media/deal/post cards |
| `media_urls` | TEXT[] | Array of CDN URLs |
| `media_metadata` | JSONB | Arbitrary metadata (e.g. file name, duration) |
| `location_lat` / `location_lon` | FLOAT | For `message_type = "location"` |
| `reply_to_id` | UUID FK → messages.id SET NULL | Quoted message |
| `deal_id` | UUID FK → group_deals.id SET NULL | Set when `message_type = "deal"` in group chat |
| `personal_deal_id` | UUID FK → personal_deals.id SET NULL | Set when `message_type = "deal"` in DM |
| `post_id` | INT FK → posts.id SET NULL | Set when `message_type = "post"` |
| `is_deleted` | BOOL | Soft delete flag |
| `sent_at` | TIMESTAMPTZ | |

Indexes: `(context_type, context_id, sent_at)` for cursor-based pagination.

### `chat_attachments`

Media files attached to a message. One row per URL in `media_urls`.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | Auto-generated |
| `message_id` | UUID FK → messages.id CASCADE | |
| `media_type` | VARCHAR(20) | `image` \| `video` \| `document` \| `audio` |
| `media_url` | VARCHAR(500) | CDN URL |
| `storage_path` | VARCHAR(500) | Internal Supabase path |
| `created_at` | TIMESTAMPTZ | |

### `personal_deals`

Deal/Requirement cards posted inside a DM. One row = one deal. A `message_type = "deal"` row in `messages` points to it via `personal_deal_id`.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | Auto-generated |
| `conversation_id` | UUID FK → conversations.id CASCADE | |
| `posted_by` | UUID FK → users.id RESTRICT | Author |
| `commodity_id` | INT FK → commodities.id | |
| `title` | VARCHAR(200) | |
| `caption` | TEXT | |
| `grain_type` | VARCHAR(50) | e.g. `"raw"`, `"processed"` |
| `grain_size` | VARCHAR(50) | |
| `commodity_quantity` | NUMERIC(12,2) | |
| `quantity_unit` | VARCHAR(20) | `MT` \| `quintal` |
| `commodity_price` | NUMERIC(12,2) | |
| `price_type` | VARCHAR(20) | `fixed` \| `negotiable` |
| `image_urls` | TEXT[] | Optional array of CDN image URLs |
| `is_closed` | BOOL | Default `false` |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

> `group_deals` schema is documented in [groups_api.md](groups_api.md). The `POST /chat/groups/{group_id}/deals` endpoint writes to that same table.

---

## 5. File Structure

```
app/modules/chat/
  domain/
    entities.py       ← Pure Python dataclasses (ConversationEntity, MessageEntity, DealSnap, ...)
    use_cases.py      ← Business rules (GetConversations, OpenChat, SendMessage, CreatePersonalDeal, ...)
  data/
    models.py         ← SQLAlchemy ORM (Conversation, ConversationMember, Message, ChatAttachment)
    repository.py     ← All DB queries (get_or_create_dm, save_message, get_conv_send_info, ...)
  presentation/
    connection_manager.py  ← Socket.IO server (sio), room joins, emit helpers, is_online check
    dependencies.py        ← FastAPI Depends factories wiring repo → use cases
    router.py              ← All REST route handlers (DM + group chat + group deals)
    schema.py              ← Pydantic request models
```

---

## 6. Socket.IO — Real-Time Connection

The server uses `python-socketio` with `AsyncServer`. Socket.IO is mounted on the same `app` that FastAPI uses — no separate port needed.

### Connecting

```dart
// Flutter — using socket_io_client
final socket = io('https://vanijyaa-backend.onrender.com', OptionBuilder()
  .setTransports(['websocket'])
  .setAuth({'token': accessToken})   // ← JWT goes here
  .build());
```

The `auth` dict must contain `"token"`. The server rejects the connection (`return False`) if the token is missing or invalid.

On successful connect, the server automatically joins the client into the room `user:{user_id}`.

### Joining group rooms

After connecting, emit `join_group` for each group the user belongs to. Call this once per group, right after `GET /groups/` returns the user's group list.

```dart
socket.emit('join_group', {'group_id': 'f47ac10b-...'});
```

No response is emitted back — fire and forget. The server verifies DB membership and silently ignores the event if the user is not a member of that group.

### Typing indicators (client → server)

The client emits `typing` while the user is composing and `stop_typing` when they pause/send. Payload identifies the chat context:

```dart
socket.emit('typing',      {'context_type': 'dm',    'context_id': convId});
socket.emit('stop_typing', {'context_type': 'group', 'context_id': groupId});
```

| Field | Type | Notes |
|---|---|---|
| `context_type` | string | `"dm"` or `"group"` |
| `context_id` | UUID | Conversation ID (DM) or group ID |

The server relays the same event name (`typing` / `stop_typing`) to the peer — to the other DM member's `user:` room, or to the `group:` room (excluding the sender). For DMs the server verifies the sender is a conversation member before relaying. Relayed payload: `{"context_type", "context_id", "user_id"}` (the `user_id` of whoever is typing).

### Events emitted by the server

| Event | Room | Fired when | Payload |
|---|---|---|---|
| `new_message` | `user:{receiver_id}` | DM message or personal deal saved | `MessageEntity` |
| `new_group_message` | `group:{group_id}` | Group chat message saved | `MessageEntity` |
| `new_group_deal` | `group:{group_id}` | Group deal created | `GroupDealResponse` |
| `conversation_accepted` | `user:{initiator_id}` | Recipient accepted the chat request | `{"conv_id": "<uuid>"}` |
| `conversation_declined` | `user:{initiator_id}` | Recipient declined the chat request | `{"conv_id": "<uuid>"}` |
| `message_deleted` | `user:{receiver_id}` (DM) / `group:{group_id}` (group) | A message was soft-deleted | `{"message_id": "<uuid>", "context_id": "<uuid>"}` |
| `read` | `user:{other_member_id}` | A DM was marked read by the other party | `{"conv_id": "<uuid>", "reader_id": "<uuid>"}` |
| `typing` / `stop_typing` | `user:{peer_id}` (DM) / `group:{group_id}` (group) | A member is composing / stopped | `{"context_type", "context_id", "user_id"}` |

`MessageEntity` and `GroupDealResponse` shapes are in [Shared Objects](#17-shared-objects).

### Disconnect

No special handling required. Socket.IO automatically removes the socket from all rooms on disconnect.

### Online presence

`is_online(user_id)` checks whether any socket is in the `user:{user_id}` room. Currently used internally only — not exposed over REST, but can be added.

---

## 7. REST API Quick Reference

Base prefix: `/chat`

All endpoints require `Authorization: Bearer <access_token>`.

| Method | Endpoint | What it does |
|---|---|---|
| `GET` | `/all` | Unified inbox — DMs + groups merged, sorted by last activity |
| `GET` | `/share/recipients` | Forward-target picker — active DMs + the user's groups |
| `GET` | `/conversations` | List the authenticated user's DM conversations |
| `POST` | `/conversations` | Start a new DM (or resume existing) + send first message |
| `GET` | `/conversations/{conv_id}/messages` | Paginated message history for a DM |
| `POST` | `/conversations/{conv_id}/messages` | Send a DM message — pushes `new_message` WS event |
| `POST` | `/conversations/{conv_id}/read` | Mark a DM as read (updates `last_read_at`) — pushes `read` to the other party |
| `POST` | `/conversations/{conv_id}/accept` | Accept a conversation request — pushes `conversation_accepted` to initiator |
| `POST` | `/conversations/{conv_id}/decline` | Decline a conversation request (blocks it) — pushes `conversation_declined` to initiator |
| `POST` | `/conversations/{conv_id}/deals` | Post a deal card into a DM — pushes `new_message` WS event |
| `POST` | `/media/upload-url` | Mint a signed Supabase upload URL for a chat attachment |
| `DELETE` | `/messages/{message_id}` | Soft-delete your own message — pushes `message_deleted`, cleans up media |
| `GET` | `/groups/{group_id}/messages` | Paginated message history for a group |
| `POST` | `/groups/{group_id}/messages` | Send a group message — pushes `new_group_message` WS event |
| `POST` | `/groups/{group_id}/deals` | Create a group deal + chat card — pushes `new_group_deal` WS event |

---

## 8. Inbox & Sharing APIs

Two list endpoints that span both DMs and groups: the **unified inbox** (the main chat screen) and the **share recipient picker** (the forward bottom-sheet).

### `GET /chat/all`

The unified inbox — every DM and every group the user belongs to, merged into **one list sorted by last activity, newest on top** (a group and a DM interleave purely by recency). This is the endpoint the main chat screen should call; `GET /chat/conversations` (DMs only) and the per-group lists remain available for narrower views.

| Query Param | Type | Default | Description |
|---|---|---|---|
| `page` | int | `1` | Page number |
| `per_page` | int | `20` | Results per page |

Each row carries a `type` discriminator and exactly one populated payload — `dm` (a [`ConversationEntity`](#conversationentity--conversation-list-item)) or `group` (a [`GroupConversationEntity`](#groupconversationentity--group-chat-list-item)). `last_activity` is the timestamp the list is sorted on (the last message's `sent_at`, falling back to the chat's creation time when there are no messages yet).

**Success `200`:**
```json
[
  {
    "type": "group",
    "last_activity": "2026-06-11T14:32:00.000000+00:00",
    "dm": null,
    "group": {
      "id": "9b1c...",
      "group_name": "Maharashtra Sugar Traders",
      "group_avatar": "https://cdn.supabase.../group.jpg",
      "member_count": 45,
      "last_message": {
        "id": "msg-uuid",
        "sender_id": "a1b2c3d4-...",
        "sender_name": "Anita Shah",
        "body": "New rate list attached.",
        "message_type": "document",
        "sent_at": "2026-06-11T14:32:00.000000+00:00"
      },
      "unread_count": 0,
      "is_muted": false,
      "created_at": "2026-05-01T09:00:00.000000+00:00",
      "updated_at": "2026-06-11T14:32:00.000000+00:00"
    }
  },
  {
    "type": "dm",
    "last_activity": "2026-06-09T10:15:00.000000+00:00",
    "dm": {
      "id": "3fa85f64-...",
      "status": "active",
      "initiator_id": "c37a3257-...",
      "participant": { /* UserSnap */ },
      "last_message": {
        "id": "msg-uuid",
        "body": "Sounds good, let me check.",
        "message_type": "text",
        "sender_id": "a1b2c3d4-...",
        "sent_at": "2026-06-09T10:15:00.000000+00:00"
      },
      "unread_count": 2,
      "is_muted": false,
      "created_at": "2026-06-08T09:00:00.000000+00:00",
      "updated_at": "2026-06-09T10:15:00.000000+00:00"
    },
    "group": null
  }
]
```

- **DM ordering** is backed by `conversations.updated_at`, which is bumped on every DM message.
- **Group ordering** is computed from the latest group message at read time (groups have no stored last-activity column).
- **`group.unread_count` is always `0`** for now — groups have no per-user read tracking (`group_members` has no `last_read_at`). DM `unread_count` is accurate. Treat group unread as "not yet implemented" rather than "zero unread".
- All of the user's DMs and groups are gathered and sorted before paging, so ordering is correct across the DM/group boundary (pagination is applied after the merge).
- DMs of **every** status are included (`requested` / `active` / `blocked`), matching `GET /chat/conversations`.

---

### `GET /chat/share/recipients`

The forward-target picker shown in the "share to chat" bottom-sheet — the two lists a user can forward a post/deal to. Lighter than `/all`: no last-message bodies or unread counts, just enough to render selectable rows.

No query parameters.

**Success `200`:**
```json
{
  "dm_connections": [
    {
      "conversation_id": "3fa85f64-...",
      "profile_id": 12,
      "user_id": "a1b2c3d4-...",
      "name": "Anita Shah",
      "avatar_url": null,
      "last_message_at": "2026-06-09T10:15:00.000000+00:00"
    }
  ],
  "groups": [
    {
      "group_id": "9b1c...",
      "name": "Maharashtra Sugar Traders",
      "avatar_url": "https://cdn.supabase.../group.jpg",
      "member_count": 45,
      "can_send": true
    }
  ]
}
```

| List | Contents | Sort |
|---|---|---|
| `dm_connections` | **Active** DMs only (`status = "active"`) | Most recent activity first |
| `groups` | Groups the user belongs to and is **not frozen** in | By group name |

- `can_send` reflects whether the user may actually post into that group right now: `true` when `chat_perm = "all_members"`, or when the user is an `admin` (so admins can always forward, even into `admins_only` groups). Render a group with `can_send = false` as disabled.
- `last_message_at` mirrors `conversations.updated_at` — use it only for ordering hints; this endpoint intentionally omits message bodies.

---

## 9. DM Conversation APIs

### `GET /chat/conversations`

List all DM conversations for the authenticated user, sorted by most recently updated.

| Query Param | Type | Default | Description |
|---|---|---|---|
| `page` | int | `1` | Page number |
| `per_page` | int | `20` | Results per page |

**Success `200`:**
```json
[
  {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "status": "active",
    "initiator_id": "c37a3257-dc3f-43be-9fb0-33cf918b11ff",
    "participant": {
      "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "profile_id": 12,
      "name": "Anita Shah",
      "is_user_verified": true,
      "is_business_verified": false,
      "avatar_url": null,
      "role": "Broker",
      "is_online": false
    },
    "last_message": {
      "id": "msg-uuid",
      "body": "Sounds good, let me check.",
      "message_type": "text",
      "sender_id": "a1b2c3d4-...",
      "sent_at": "2026-06-09T10:15:00.000000+00:00"
    },
    "unread_count": 2,
    "is_muted": false,
    "created_at": "2026-06-08T09:00:00.000000+00:00",
    "updated_at": "2026-06-09T10:15:00.000000+00:00"
  }
]
```

- `participant` — the other user in the conversation (not the caller).
- `unread_count` — messages received since the caller's `last_read_at`.
- `is_online` — always `false` from the REST layer; use Socket.IO presence for live state.

---

### `POST /chat/conversations`

Start a new DM conversation and send the first message. If a DM with this participant already exists, it is reused and the message is appended.

**Request body:**
```json
{
  "participant_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "first_message": "Hi, are you interested in buying 200 MT rice?"
}
```

| Field | Required | Notes |
|---|---|---|
| `participant_id` | Yes | UUID of the other user |
| `first_message` | Yes | 1–4000 characters |

**Success `201`:**
```json
{
  "conversation": { /* ConversationEntity */ },
  "message": { /* MessageEntity */ },
  "created": true
}
```

- `created: true` → new conversation was started; `false` → existing conversation was reused.
- The conversation starts in `status: "requested"`. The receiver must call `/accept` before they can reply.

**WS push:** fires `new_message` to `user:{participant_id}` with the first `MessageEntity`.

**Error `400`** — chatting with yourself:
```json
{ "detail": "Cannot chat with yourself" }
```

**Error `403`** — conversation is blocked:
```json
{ "detail": "This convo is blocked" }
```

---

## 10. DM Message APIs

### `GET /chat/conversations/{conv_id}/messages`

Paginated message history for a DM, newest first. Use cursor-based pagination via `before`.

| Query Param | Type | Default | Description |
|---|---|---|---|
| `before` | datetime (ISO 8601) | — | Return messages sent before this timestamp (cursor) |
| `limit` | int | `50` | Messages per page (max 100) |

**Example — first load:**
```
GET /chat/conversations/3fa85f64-.../messages?limit=50
```

**Example — load older messages:**
```
GET /chat/conversations/3fa85f64-.../messages?before=2026-06-09T10:00:00Z&limit=50
```

**Success `200`** — array of `MessageEntity` objects, newest first:
```json
[
  {
    "id": "msg-uuid-1",
    "context_id": "3fa85f64-...",
    "context_type": "dm",
    "sender": { /* UserSnap */ },
    "message_type": "text",
    "body": "Sounds good.",
    "media_urls": null,
    "media_metadata": null,
    "location_lat": null,
    "location_lon": null,
    "reply_to_id": null,
    "is_deleted": false,
    "sent_at": "2026-06-09T10:15:00.000000+00:00",
    "deal": null,
    "post": null
  }
]
```

**Error `403`** — caller is not a member of this conversation:
```json
{ "detail": "the user is not a part of this convo" }
```

---

### `POST /chat/conversations/{conv_id}/messages`

Send a message in an existing DM. Also fires a `new_message` Socket.IO event to the receiver in the background.

**Send rules enforced server-side:**

| Conversation status | Who can send |
|---|---|
| `blocked` | Nobody — `403` |
| `requested` | Only the initiator (who sent the first message) |
| `active` | Both participants |

**Request body:**
```json
{
  "body": "I can offer 300 MT at ₹41,000/MT.",
  "message_type": "text",
  "media_urls": null,
  "media_metadata": null,
  "location_lat": null,
  "location_lon": null,
  "reply_to_id": null,
  "deal_id": null,
  "personal_deal_id": null,
  "post_id": null
}
```

| Field | Required | Type | Notes |
|---|---|---|---|
| `body` | Conditional | string | Required for `text`; null for media/deal/post |
| `message_type` | No | string | Default `"text"` — see [Message Types](#16-message-types) |
| `media_urls` | No | string[] | CDN URLs of uploaded files |
| `media_metadata` | No | dict | Arbitrary metadata (filename, duration, etc.) |
| `location_lat` / `location_lon` | No | float | For `message_type = "location"` |
| `reply_to_id` | No | UUID | ID of the message being quoted |
| `deal_id` | No | UUID | FK to `group_deals.id` — share a group deal into DM |
| `personal_deal_id` | No | UUID | FK to `personal_deals.id` — reference an existing personal deal |
| `post_id` | No | int | FK to `posts.id` — share a post into DM. Validated: a non-existent id returns `404` |

**Success `201`** — returns a `MessageEntity`.

**WS push:** fires `new_message` to `user:{receiver_id}` with the same `MessageEntity` payload.

**Error `404`** — conversation not found:
```json
{ "detail": "Conversation not found." }
```

**Error `404`** — `post_id` references a post that doesn't exist (prevents an orphan post card):
```json
{ "detail": "Post not found." }
```

**Error `403`:**
```json
{ "detail": "Waiting for the other person to accept." }
```

---

### `POST /chat/conversations/{conv_id}/read`

Mark a conversation as read. Sets `last_read_at = now()` for the authenticated user. This resets `unread_count` to 0 from the caller's perspective.

No request body.

**Success `200`:**
```json
{ "ok": true }
```

**WS push:** fires `read` to the other member's `user:{id}` room with `{"conv_id": "<uuid>", "reader_id": "<caller-uuid>"}`, so the sender can flip their message ticks to "read".

---

### `POST /chat/conversations/{conv_id}/accept`

Accept a pending conversation request. **Must be the receiver** (not the initiator). Changes status from `requested` → `active`. Both participants can now send messages freely.

No request body.

**Success `200`** — returns updated `ConversationEntity`.

**WS push:** fires `conversation_accepted` to `user:{initiator_id}` with `{"conv_id": "<uuid>"}`.

**Error `409`** — conversation is not in `requested` state:
```json
{ "detail": "cannot accept : conversation already - 'active'." }
```

---

### `POST /chat/conversations/{conv_id}/decline`

Decline and block a conversation. Changes status from `requested` → `blocked`. Neither participant can send messages after this.

No request body.

**Success `200`** — returns updated `ConversationEntity`.

**WS push:** fires `conversation_declined` to `user:{initiator_id}` with `{"conv_id": "<uuid>"}`.

---

## 11. Media Upload & Message Deletion

### Media upload — the 3-step flow

Chat media (images, video, audio, documents) is **never sent to the backend as file bytes**. The client uploads straight to Supabase Storage; the backend only mints a short-lived signed URL and later stores the resulting public URL on the message.

```
1. Client  → POST /chat/media/upload-url?content_type=audio/mp4   (backend mints signed URL)
2. Client  → PUT <upload_url> with the raw bytes                  (direct to Supabase, Content-Type must match)
3. Client  → POST /chat/conversations/{id}/messages              (send msg with media_url in media_urls)
              { "message_type": "audio", "media_urls": ["<media_url>"] }
```

Files land in the `chat` bucket (env `CHAT_STORAGE_BUCKET`) at path `{user_id}/{uuid}.{ext}`. The signed URL expires in 5 minutes.

### `POST /chat/media/upload-url`

Mint a signed upload URL for a chat attachment. Per-user scoped — any authenticated user may call it; no conversation/group membership is checked at this step.

| Query Param | Type | Required | Description |
|---|---|---|---|
| `content_type` | string | Yes | MIME type of the file being uploaded — must be in the allowlist below |

**Allowed `content_type` values:**

| Category | MIME types |
|---|---|
| Image | `image/jpeg`, `image/png`, `image/webp` |
| Video | `video/mp4`, `video/quicktime`, `video/webm` |
| Audio | `audio/mpeg`, `audio/mp4`, `audio/webm`, `audio/ogg` |
| Document | `application/pdf` |

**Success `201`:**
```json
{
  "upload_url": "https://wnkjqmdoosbtukjbzknu.supabase.co/storage/v1/object/upload/sign/chat/...",
  "expires_at": "2026-06-10T10:05:00+00:00",
  "media_url": "https://wnkjqmdoosbtukjbzknu.supabase.co/storage/v1/object/public/chat/<user_id>/<uuid>.mp4",
  "content_type": "audio/mp4"
}
```

| Field | Description |
|---|---|
| `upload_url` | Signed PUT target — upload the raw bytes here within 5 min. The `Content-Type` header on the PUT **must equal** the `content_type` you requested |
| `media_url` | The public URL to put in `media_urls` when sending the message |
| `expires_at` | ISO 8601 expiry of `upload_url` |

**Error `400`** — unsupported content type:
```json
{ "detail": "Unsupported type 'audio/3gpp'. Allowed: image/jpeg, image/png, image/webp, ..." }
```

**Error `503`** — Supabase Storage unavailable.

> **Cleanup tracking:** When the message is later sent, the backend derives the internal `storage_path` from `media_url` and stores it on the `chat_attachments` row, so the object can be removed if the message is deleted. URLs that don't belong to the `chat` bucket are accepted but won't be tracked for cleanup.

---

### `DELETE /chat/messages/{message_id}`

Soft-delete a message. **Only the original sender may delete their own message** (works for both DM and group messages). Sets `is_deleted = true`; the attached media object is removed from the `chat` bucket in a background task.

No request body.

**Success `200`:**
```json
{ "ok": true, "message_id": "d4e5f6a7-..." }
```

**WS push:**
- DM → fires `message_deleted` to the other member's `user:{id}` room
- Group → fires `message_deleted` to the `group:{group_id}` room

Payload: `{"message_id": "<uuid>", "context_id": "<uuid>"}`. Clients should replace the bubble with a "This message was deleted" placeholder.

**Error `404`** — message not found, already deleted, or the caller is not the sender:
```json
{ "detail": "Message not found or you cannot delete it." }
```

---

## 12. Personal Deal APIs

Personal deals are Deal/Requirement cards created inside a DM. The deal is saved and a `message_type = "deal"` chat card is automatically inserted — there is no separate "send the message" step.

### `POST /chat/conversations/{conv_id}/deals`

Post a deal card into a DM. **Conversation must be `active`.**

After saving, fires a `new_message` Socket.IO event to the receiver with the deal message card.

**Request body:**
```json
{
  "commodity_id": 1,
  "title": "Grade A Basmati — Private Offer",
  "caption": "200 MT available. Serious buyers only.",
  "grain_type": "raw",
  "grain_size": "long",
  "commodity_quantity": 200,
  "quantity_unit": "MT",
  "commodity_price": 42000,
  "price_type": "negotiable",
  "image_urls": ["https://cdn.supabase.../deal-image.jpg"]
}
```

| Field | Required | Type | Notes |
|---|---|---|---|
| `commodity_id` | Yes | int | FK to commodities table |
| `title` | Yes | string | 1–200 characters |
| `caption` | Yes | string | Min 1 character |
| `grain_type` | Yes | string | e.g. `"raw"`, `"processed"` |
| `grain_size` | Yes | string | e.g. `"long"`, `"medium"`, `"fine"` |
| `commodity_quantity` | Yes | float | Quantity offered/requested |
| `quantity_unit` | Yes | string | `MT` \| `quintal` |
| `commodity_price` | Yes | float | Price per unit |
| `price_type` | Yes | string | `fixed` \| `negotiable` |
| `image_urls` | No | string[] | CDN URLs of deal images |

**Success `201`** — returns a `MessageEntity` with `message_type = "deal"` and the `deal` field populated as a `DealSnap`.

**Error `403`** — conversation is not `active`:
```json
{ "detail": "Can only create deals in an active conversation." }
```

**Error `404`** — conversation not found or caller is not a member:
```json
{ "detail": "Conversation not found." }
```

---

## 13. Group Chat APIs

### `GET /chat/groups/{group_id}/messages`

Paginated message history for a group, newest first. **Must be a group member.**

| Query Param | Type | Default | Description |
|---|---|---|---|
| `before` | datetime (ISO 8601) | — | Cursor — return messages before this timestamp |
| `limit` | int | `50` | Messages per page (max 100) |

**Success `200`** — array of `MessageEntity` objects.

**Error `403`** — not a member:
```json
{ "detail": "Not a member of this group." }
```

---

### `POST /chat/groups/{group_id}/messages`

Send a message into a group. Also fires a `new_group_message` Socket.IO event to the group room.

**Send rules enforced server-side:**

| Condition | Result |
|---|---|
| Not a group member | `403` |
| `is_frozen = true` | `403` |
| `chat_perm = admins_only` and caller is not admin | `403` |

**Request body:**
```json
{
  "body": "Anyone selling 500 MT of sugar this week?",
  "message_type": "text",
  "media_urls": null,
  "media_metadata": null,
  "location_lat": null,
  "location_lon": null,
  "reply_to_id": null,
  "deal_id": null,
  "post_id": null
}
```

| Field | Required | Type | Notes |
|---|---|---|---|
| `body` | Conditional | string | Required for `text`; null for other types |
| `message_type` | No | string | Default `"text"` — see [Message Types](#16-message-types) |
| `media_urls` | No | string[] | CDN URLs of uploaded files |
| `media_metadata` | No | dict | Arbitrary metadata |
| `location_lat` / `location_lon` | No | float | For `message_type = "location"` |
| `reply_to_id` | No | UUID | Quoted message ID |
| `deal_id` | No | UUID | Reference an existing group deal (FK → group_deals.id) |
| `post_id` | No | int | Share a post into group chat. Validated: a non-existent id returns `404` |

> **Note:** `personal_deal_id` is not accepted in group messages — personal deals belong to DMs only.

**Success `201`** — returns a `MessageEntity`.

**WS push:** fires `new_group_message` to `group:{group_id}`.

**Error `404`** — `post_id` references a post that doesn't exist:
```json
{ "detail": "Post not found." }
```

---

## 14. Group Deal APIs (Chat)

Group deals live in the `group_deals` table (shared with the groups module) but their **creation endpoint is here** — because creating a deal needs to write a chat card and push a Socket.IO event, which requires the chat module's infrastructure.

> Read/update/close/publish endpoints for group deals are still in the groups module: `GET|PATCH|POST /api/v1/groups/{group_id}/deals/...` — see [groups_api.md](groups_api.md).

### `POST /chat/groups/{group_id}/deals`

Create a group deal. In one atomic transaction this:
1. Inserts a `group_deals` row.
2. Inserts a `messages` row with `message_type = "deal"` pointing to the new deal (`deal_id` FK).

After the transaction, fires a `new_group_deal` Socket.IO event to the group room.

**Permission rules:**

| Condition | Result |
|---|---|
| Not a group member | `403` |
| `posting_perm = admins_only` and caller is not admin | `403` |
| Caller's `is_frozen = true` | `403` |

**Request body:**
```json
{
  "commodity_id": 1,
  "title": "Fresh Basmati Rice — Bulk Available",
  "caption": "Grade A Basmati, 500 MT available immediately. DM for FOB pricing.",
  "grain_type": "raw",
  "grain_size": "long",
  "commodity_quantity": 500,
  "quantity_unit": "MT",
  "commodity_price": 42000,
  "price_type": "negotiable",
  "image_urls": ["https://cdn.supabase.../deal-img.jpg"],
  "publish_to_feed": false,
  "feed_is_public": true
}
```

| Field | Required | Type | Notes |
|---|---|---|---|
| `commodity_id` | Yes | int | FK to commodities table |
| `title` | Yes | string | 1–200 characters |
| `caption` | Yes | string | Min 1 character |
| `grain_type` | Yes | string | e.g. `"raw"`, `"processed"` |
| `grain_size` | Yes | string | e.g. `"long"`, `"medium"`, `"fine"` |
| `commodity_quantity` | Yes | float | Quantity offered/requested |
| `quantity_unit` | Yes | string | `MT` \| `quintal` |
| `commodity_price` | Yes | float | Price per unit |
| `price_type` | Yes | string | `fixed` \| `negotiable` |
| `image_urls` | No | string[] | CDN URLs of deal images |
| `publish_to_feed` | No | bool | `false` (default) — also create a public `Post` entry |
| `feed_is_public` | No | bool | `true` (default) — controls the Post's visibility |

**Success `201`** — returns a `GroupDealResponse` (see [groups_api.md](groups_api.md#15-shared-objects)).

**WS push:** fires `new_group_deal` to `group:{group_id}` with the `GroupDealResponse` payload.

**Error `403`:**
```json
{ "detail": "Only admins can post deals in this group" }
```

---

## 15. Conversation Status Flow

```
(User A sends first message)
         ↓
    status: "requested"
    → Only User A (initiator) can send more messages
    → User B sees it in their conversation list
         ↓
    User B calls POST /conversations/{id}/accept
         ↓
    status: "active"
    → Both can send freely
         ↓
    User B calls POST /conversations/{id}/decline
         ↓
    status: "blocked"
    → Nobody can send
```

| Status | Who can send | Notes |
|---|---|---|
| `requested` | Initiator only | Receiver sees it as a message request |
| `active` | Both participants | Normal chat |
| `blocked` | Nobody | Created when receiver declines |

---

## 16. Message Types

| `message_type` | When to use | Which fields to populate |
|---|---|---|
| `text` | Plain text message | `body` required |
| `image` | Photo(s) | `media_urls`, optionally `body` as caption |
| `video` | Video clip | `media_urls`, optionally `body` |
| `document` | PDF / file | `media_urls`, `media_metadata` for filename |
| `audio` | Voice note | `media_urls`, `media_metadata` for duration |
| `location` | Pin on map | `location_lat`, `location_lon` |
| `deal` | Deal card — auto-set by `/deals` endpoints | Do not set manually; `deal` field in response is populated |
| `post` | Shared post card | `post_id` required; `post` field in response is populated |

---

## 17. Shared Objects

### `UserSnap` — sender/participant profile

Embedded inside `MessageEntity` and `ConversationEntity`.

```json
{
  "user_id": "c37a3257-dc3f-43be-9fb0-33cf918b11ff",
  "profile_id": 5,
  "name": "Ravi Traders",
  "is_user_verified": true,
  "is_business_verified": true,
  "avatar_url": "https://cdn.supabase.../avatar.jpg",
  "role": "Trader",
  "is_online": true
}
```

- `is_online` — live from Socket.IO room membership when set by the presentation layer; `false` in REST list responses.

---

### `MessageEntity` — message payload

Returned by send/get message endpoints and carried by `new_message` / `new_group_message` WS events.

```json
{
  "id": "msg-uuid",
  "context_id": "conv-or-group-uuid",
  "context_type": "dm",
  "sender": { /* UserSnap */ },
  "message_type": "text",
  "body": "Hi there!",
  "media_urls": null,
  "media_metadata": null,
  "location_lat": null,
  "location_lon": null,
  "reply_to_id": null,
  "is_deleted": false,
  "sent_at": "2026-06-09T10:15:00.000000+00:00",
  "deal": null,
  "post": null
}
```

When `message_type = "deal"`, the `deal` field is a `DealSnap`:

```json
"deal": {
  "deal_id": "e1f2a3b4-...",
  "title": "Fresh Basmati Rice",
  "commodity_name": "Basmati Rice",
  "grain_type": "raw",
  "grain_size": "long",
  "commodity_quantity": 500.0,
  "quantity_unit": "MT",
  "commodity_price": 42000.0,
  "price_type": "negotiable",
  "image_urls": ["https://cdn.supabase.../deal-img.jpg"],
  "is_closed": false,
  "caption": "Grade A Basmati, available immediately."
}
```

When `message_type = "post"`, the `post` field is a `PostSnap`:

```json
"post": {
  "post_id": 1042,
  "title": "Rice Market Update — June 2026",
  "image_urls": null,
  "caption": "Prices trending up this week...",
  "category_id": 1,
  "category_name": "Market Update",
  "author_name": "Ravi Traders"
}
```

---

### `ConversationEntity` — conversation list item

```json
{
  "id": "3fa85f64-...",
  "status": "active",
  "initiator_id": "c37a3257-...",
  "participant": { /* UserSnap */ },
  "last_message": {
    "id": "msg-uuid",
    "body": "Sounds good.",
    "message_type": "text",
    "sender_id": "a1b2c3d4-...",
    "sent_at": "2026-06-09T10:15:00.000000+00:00"
  },
  "unread_count": 2,
  "is_muted": false,
  "created_at": "2026-06-08T09:00:00.000000+00:00",
  "updated_at": "2026-06-09T10:15:00.000000+00:00"
}
```

---

### `GroupConversationEntity` — group chat list item

The group counterpart of `ConversationEntity`, returned inside `GET /chat/all` rows where `type = "group"`.

```json
{
  "id": "9b1c...",
  "group_name": "Maharashtra Sugar Traders",
  "group_avatar": "https://cdn.supabase.../group.jpg",
  "member_count": 45,
  "last_message": {
    "id": "msg-uuid",
    "sender_id": "a1b2c3d4-...",
    "sender_name": "Anita Shah",
    "body": "New rate list attached.",
    "message_type": "document",
    "sent_at": "2026-06-11T14:32:00.000000+00:00"
  },
  "unread_count": 0,
  "is_muted": false,
  "created_at": "2026-05-01T09:00:00.000000+00:00",
  "updated_at": "2026-06-11T14:32:00.000000+00:00"
}
```

- `last_message` is a `GroupLastMessage` (note it carries `sender_name` so the list can show "Anita: …" without an extra lookup), or `null` if the group has no messages yet.
- `unread_count` is currently always `0` — see the note under [`GET /chat/all`](#get-chatall).
- `updated_at` mirrors the last message's `sent_at` (or `created_at` when empty); groups have no stored `updated_at` column.

---

### `ChatListItem` — unified inbox row

The envelope returned by `GET /chat/all`. Exactly one of `dm` / `group` is non-null; `type` tells you which.

```json
{
  "type": "dm",
  "last_activity": "2026-06-09T10:15:00.000000+00:00",
  "dm": { /* ConversationEntity */ },
  "group": null
}
```

| Field | Type | Notes |
|---|---|---|
| `type` | string | `"dm"` or `"group"` |
| `last_activity` | datetime | Sort key — newest first |
| `dm` | ConversationEntity \| null | Set when `type = "dm"` |
| `group` | GroupConversationEntity \| null | Set when `type = "group"` |

---

### `ShareRecipientsResult` — forward picker payload

Returned by `GET /chat/share/recipients`.

```json
{
  "dm_connections": [
    {
      "conversation_id": "3fa85f64-...",
      "profile_id": 12,
      "user_id": "a1b2c3d4-...",
      "name": "Anita Shah",
      "avatar_url": null,
      "last_message_at": "2026-06-09T10:15:00.000000+00:00"
    }
  ],
  "groups": [
    {
      "group_id": "9b1c...",
      "name": "Maharashtra Sugar Traders",
      "avatar_url": "https://cdn.supabase.../group.jpg",
      "member_count": 45,
      "can_send": true
    }
  ]
}
```

- **`ShareDMItem`** (`dm_connections[]`): `conversation_id`, `profile_id`, `user_id`, `name`, `avatar_url`, `last_message_at`.
- **`ShareGroupItem`** (`groups[]`): `group_id`, `name`, `avatar_url`, `member_count`, `can_send`.

---

## 18. Error Reference

All errors follow FastAPI's standard shape:
```json
{ "detail": "Human-readable message." }
```

| Status | When it happens |
|---|---|
| `401` | Missing or invalid Bearer token; Socket.IO connection with invalid token (connection rejected) |
| `403` | Not a conversation member / conversation is blocked / waiting for acceptance / frozen group member / chat permission violation / deal posted in inactive conversation |
| `404` | Conversation not found / group not found / shared `post_id` references a non-existent post |
| `409` | Conversation status already resolved (e.g. accepting an already-active conversation) |
| `422` | Missing required field, invalid `message_type`, invalid `quantity_unit`, invalid `price_type` |
