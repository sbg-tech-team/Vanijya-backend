# Open DM Migration — Frontend Contract

**What changed:** The message request pipeline has been bypassed. Any user can now DM any other user directly — no request/accept flow required.

---

## What the app NO LONGER needs to call

These endpoints still exist on the backend but are paused. Stop calling them:

| Endpoint | Was used for |
|---|---|
| `POST /connections/message-request/{target_id}` | Sending a message request |
| `PATCH /connections/message-request/{id}/accept` | Accepting a request |
| `PATCH /connections/message-request/{id}/decline` | Declining a request |
| `GET /connections/message-requests/received` | Inbox of pending requests |
| `GET /connections/message-requests/sent` | Sent requests list |

**WebSocket events to stop listening for:**
- `message_request_accepted`
- `message_request_declined`

---

## What the app does instead

### Open or get a DM conversation

**`POST /chat/conversations`**

Auth: Bearer token required

Works for **any two users** — no follow relationship required.

**Request body:**
```json
{
  "participant_id": "<user_uuid>"
}
```

**Response `200`:**
```json
{
  "id": "<conversation_uuid>",
  "status": "active",
  "created": true
}
```

| Field | Meaning |
|---|---|
| `id` | Conversation UUID — use this to navigate to the chat screen and to send messages |
| `status` | Always `"active"` for new conversations |
| `created` | `true` if a new conversation was just created, `false` if one already existed |

**Idempotent** — safe to call multiple times for the same pair of users. Always returns the same conversation.

### "Message" button flow

```
User taps "Message" on any profile
        ↓
POST /chat/conversations  { participant_id: target_user_id }
        ↓
Navigate to chat screen using response.id
        ↓
POST /chat/conversations/{id}/messages  (send normally)
```

---

## Share sheet changes

**`GET /chat/share/recipients`**

The DM list in the share sheet now returns **people you follow** instead of only previously active DMs.

Each DM item now has `conversation_id` which may be `null`:

```json
{
  "dm_connections": [
    {
      "conversation_id": "<uuid or null>",
      "user_id": "<uuid>",
      "profile_id": 42,
      "name": "Ravi Mehta",
      "avatar_url": "https://...",
      "last_message_at": "2026-06-25T10:00:00Z"
    }
  ],
  "groups": [ ... ]
}
```

**If `conversation_id` is `null`** — no DM exists yet with this person. Before sharing:
1. Call `POST /chat/conversations` with `participant_id = user_id`
2. Use the returned `id` as the conversation to deliver to

**Ranking:**
- People with an existing DM → sorted by most recent message first
- People you follow but never DM'd → sorted alphabetically by name (appear below)

---

## Conversation status

All conversations now start as `"active"` — there is no `"requested"` state anymore.

| Old status | New status |
|---|---|
| `"requested"` | `"active"` |
| `"active"` | `"active"` (unchanged) |
| `"blocked"` | `"blocked"` (unchanged — not used in this phase) |

The `status` field is still returned in conversation responses. No action needed — just ignore `"requested"` if you ever see it.

---

## Fields that still exist but can be ignored

These are still returned by some API responses. The backend has not removed them. You can safely ignore them:

| Field | Where it appears |
|---|---|
| `message_request_status` | `GET /profile/{id}` response |
| `msg_req_status` | Connection status responses |

---

## Endpoint summary

| Endpoint | Status | Notes |
|---|---|---|
| `POST /chat/conversations` | **NEW** | Open/get DM — replaces message request flow |
| `GET /chat/share/recipients` | **CHANGED** | Now returns following list, `conversation_id` may be null |
| `POST /connections/message-request/{id}` | Paused | Do not call |
| `PATCH /connections/message-request/{id}/accept` | Paused | Do not call |
| `PATCH /connections/message-request/{id}/decline` | Paused | Do not call |
| `GET /connections/message-requests/received` | Paused | Do not call |
| `GET /connections/message-requests/sent` | Paused | Do not call |
