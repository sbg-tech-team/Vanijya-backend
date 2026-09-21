# Calling API — Frontend Contract

**Base URL:** `https://vanijya-backend-7fuf.onrender.com`
**Auth:** every endpoint needs `Authorization: Bearer <access_token>`.
**Status:** live in production. Verified against the deployed service on 2026-09-21 —
every payload below is a real captured response, not an example.

Audio only. Video returns `501` today.

---

## 1. How it fits together

Stream carries the audio. The backend owns everything else: who may call whom, ringing,
push, state, history, duration. You never call Stream's API to create or manage a call —
you call us, we hand back a short-lived Stream token, and you use that token *only* to
join the media session.

```
caller                    backend                     callee
  |  POST /calls             |                          |
  |------------------------->|  socket: incoming_call   |
  |  201 + stream creds      |------------------------->|
  |                          |  FCM data push           |
  |                          |------------------------->|
  |                          |  POST /calls/{id}/accept |
  |  socket: call_accepted   |<-------------------------|
  |<-------------------------|  200 + stream creds      |
  |                          |------------------------->|
  |        ==== both join Stream with their token ====  |
  |  POST /calls/{id}/end    |                          |
  |------------------------->|  socket: call_ended      |
  |  200                     |------------------------->|
```

Every response is wrapped:

```json
{ "success": true, "message": "Call initiated", "data": { ... } }
```

`data` is documented below. Errors are **not** wrapped — they are `{"detail": ...}`.

---

## 2. Endpoints

### POST /calls — start a call

```json
{ "call_type": "dm", "target_user_id": "<uuid>", "media": "audio" }
```

For a group call send `{"call_type": "group", "group_id": "<uuid>", "media": "audio"}`.
Sending both `target_user_id` and `group_id`, or neither, is a `422`.

**201**

```json
{
  "call_id": "e109fda7-3609-4819-9769-1f8eb2ebe4ed",
  "call_type": "dm",
  "media": "audio",
  "status": "ringing",
  "created_at": "2026-09-21T09:25:05.269672Z",
  "started_at": null,
  "ring_timeout_seconds": 45,
  "stream": {
    "api_key": "3qxkdqapz4vs",
    "token": "eyJhbGciOiJIUzI1NiIs...",
    "user_id": "4a999b51-cd9a-455c-b43b-f10719daf57c",
    "call_type": "default",
    "call_id": "e109fda73609481997691f8eb2ebe4ed"
  },
  "participants": [
    {
      "user_id": "4a999b51-cd9a-455c-b43b-f10719daf57c",
      "profile_id": 131,
      "name": "Ghanashvee Sakhare",
      "avatar_url": "https://…/avatars/131.jpg",
      "role": "caller",
      "state": "joined"
    },
    {
      "user_id": "93a26bcc-c5bc-4b4c-b1a2-80178a61c18e",
      "profile_id": 130,
      "name": "vg",
      "avatar_url": null,
      "role": "callee",
      "state": "ringing"
    }
  ]
}
```

Note `stream.call_id` is the **un-hyphenated** form of `call_id`. That is the id Stream
expects; use it with `stream.call_type` (`"default"`) when joining.

### GET /calls/{call_id} — current state

Same shape as above, except **`stream` is `null`**. State polling never mints a token —
use `POST /calls/{id}/token` for that.

### POST /calls/{call_id}/accept — callee answers

No body. **200** returns the same object with `status: "active"`, `started_at` set,
`ring_timeout_seconds: null`, and a `stream` block scoped to the accepting user.

Only the callee may accept. The caller gets `403 "You cannot accept a call you started."`

### POST /calls/{call_id}/reject — callee declines

No body. **200**. 1:1 reject ends the call for both sides; a group reject only removes you.
The caller gets `403 "You cannot reject a call you started."` — to cancel your own
unanswered call use `POST /calls/{id}/end`, which records it as `cancelled`.

### POST /calls/{call_id}/token — refresh the Stream token

No body. **200**

```json
{ "token": "eyJhbGciOiJIUzI1NiIs...", "expires_at": "2026-09-21T10:25:13Z" }
```

Tokens are short-lived (1 hour). Refresh before expiry on a long call.

**Who may call it:** any participant whose state is `joined`. The caller is inserted
as `joined` the moment the call is created, so **the caller can always re-mint** —
including after an app restart, without ever hitting `/accept`. That is the supported
way back into the media session: `GET /calls/{id}` on resume, then `POST /calls/{id}/token`.

A callee who has not yet accepted is still `ringing`, and gets
`409 "Accept the call before requesting a token."` Accepting first is the only path
for them; minting early would join the media session while the call still counted as
unanswered.

### POST /calls/{call_id}/heartbeat — prove you are still there

No body. **200**

```json
{ "call_id": "e109fda7-…", "status": "active", "next_heartbeat_in_seconds": 30 }
```

**Send this every 30 s while in a call.** If heartbeats stop for 90 s the backend assumes
every client is gone and tears the call down — that is what stops billing when an app is
force-quit. Honour `next_heartbeat_in_seconds` rather than hard-coding the interval.

**During `ringing`:** allowed, returns `200` with `status: "ringing"`, but **not required**.
The ring timeout is driven by the call's `created_at`, not by heartbeats, so a caller who
starts heartbeating only on `active` is behaving correctly. Only the 90 s teardown uses
them, and that applies to `active` calls.

### POST /calls/{call_id}/end — hang up

No body. **200**

```json
{
  "call_id": "e109fda7-…",
  "status": "ended",
  "started_at": "2026-09-21T09:25:11.232960Z",
  "ended_at": "2026-09-21T09:25:15.373013Z",
  "duration_seconds": 4,
  "end_reason": "hung_up"
}
```

### GET /calls — history

Query params, all optional: `limit`, `cursor`, `call_type` (`dm` | `group`).

**200**

```json
{
  "calls": [
    {
      "call_id": "e109fda7-…",
      "call_type": "dm",
      "media": "audio",
      "status": "ended",
      "direction": "outgoing",
      "end_reason": "hung_up",
      "created_at": "2026-09-21T09:25:05.269672Z",
      "started_at": "2026-09-21T09:25:11.232960Z",
      "ended_at": "2026-09-21T09:25:15.373013Z",
      "duration_seconds": 4,
      "counterparty": {
        "user_id": "93a26bcc-…", "profile_id": 130,
        "name": "vg", "avatar_url": null
      },
      "group": null,
      "participant_count": 2
    }
  ],
  "next_cursor": null
}
```

`direction` is `"outgoing"` or `"incoming"`, computed per requesting user on every read —
the same call is `outgoing` for the caller and `incoming` for the callee. For a group call
`counterparty` is `null` and `group` is populated. Page with `next_cursor` when it is
non-null.

`media` is always present on every row, DM and group alike; an example above that omits it
is an omission in the example, not an optional field. History rows deliberately carry no
`stream` block (nothing to join) and no `participants` array — a group row gives
`participant_count` only. Open `GET /calls/{id}` if you need the full participant list.

### POST /calls/devices — register this device so it rings

```json
{ "fcm_token": "dXNlcl9kZXZpY2VfdG9rZW4...", "platform": "android", "token_type": "fcm" }
```

`platform` is optional, one of `ios` · `android` · `web`.
`token_type` is optional and defaults to `"fcm"`, one of `fcm` · `voip`. **201**

```json
{ "success": true, "message": "Device registered",
  "data": { "registered": true, "deliverable": true } }
```

#### iOS: which token to send

An iPhone holds two push tokens and they cannot be told apart by value, so
`token_type` is what distinguishes them:

| Token | `token_type` | Deliverable today |
|---|---|---|
| FCM registration token (`Messaging.messaging().token`) | `"fcm"` | **yes** |
| PushKit VoIP token (`PKPushRegistry`) | `"voip"` | **no — stored only** |

Send both. A VoIP token is accepted and stored, but the response comes back with
`"deliverable": false` and nothing pushes to it yet: a PushKit token is a raw APNs
device token, so Firebase cannot deliver to it at all, and it needs a direct-APNs
sender on the `<bundle-id>.voip` topic that we have not built. Registering it now
means the day that ships, every device is already enrolled.

**Until then, iOS rings only while the app is foreground or backgrounded, not killed.**
A data-only FCM message is an APNs *background* push, which iOS throttles and will not
use to launch a terminated app. Android is unaffected — it gets `priority: high` and
wakes reliably.

Do not send a VoIP token as `token_type: "fcm"`. It will be rejected by FCM on the next
call and then deleted as a dead token, so that device stops being enrolled entirely.

**Call this on every sign-in and on every FCM token refresh.** Tokens are stored one row
per device, so a phone and a tablet both ring and the first to answer wins — the others
get `call_answered_elsewhere`.

Registering a token that already exists moves it to the calling user, so a handset handed
to someone else stops ringing the previous owner. Tokens that FCM reports as
`UNREGISTERED` (app uninstalled, token rotated) are deleted automatically on the next
push, per token — one dead device never affects the others.

### GET /calls/usage — budget

**200**

```json
{
  "user_minutes_today": 1,
  "user_daily_limit": 600,
  "platform_minutes_this_month": 10,
  "platform_monthly_limit": 300000
}
```

Two Redis reads, no database — cheap enough to call when the call screen opens, and
the intended way to warn a user before they hit the `429` rather than failing the call.

**Returns `{}` (empty object, still `200`) when Redis is unavailable.** Treat a missing
key as "unknown", not as zero, or a Redis blip will tell every user they have no minutes
left.

### The in-chat call card

Every finished call also writes one message into the conversation, delivered through the
existing `GET /chat/conversations/{id}/messages` and `new_message` / `new_group_message`
socket events. `message_type` is `"call"`:

```json
{
  "id": "...",
  "message_type": "call",
  "sender": { "user_id": "...", "name": "Ramesh Patel", "avatar_url": "..." },
  "body": null,
  "call": {
    "call_id": "...",
    "media": "audio",
    "status": "ended",
    "end_reason": "hung_up",
    "duration_seconds": 265
  },
  "sent_at": "2026-09-21T11:23:47Z"
}
```

**There is no `direction` field on this object, by design.** One message row is shared by
both participants, so a stored direction would be wrong for one of them. `sender` is the
call initiator — compare it to your own user id: equal means outgoing, otherwise incoming.

(`direction` *does* exist on `GET /calls` history rows, where it is computed per
requesting user on every read.)

---

## 3. Socket events

Socket.IO, same connection as chat, authenticated with `{"token": "<access_token>"}`.
Events arrive in the user's own room — no subscribe step.

| Event | Sent to | When |
|---|---|---|
| `incoming_call` | callee(s) | a call starts — payload is the full call object with `stream: null` |
| `call_accepted` | caller | callee answered |
| `call_answered_elsewhere` | callee's other devices | answered on one device; stop ringing here |
| `call_rejected` | caller | callee declined |
| `call_cancelled` | callee(s) | caller hung up before an answer |
| `call_ended` | everyone | call finished — `{call_id, ended_by, ended_at, duration_seconds, end_reason}`. `ended_by` is `null` when the backend ended it (timeout, reaper) rather than a person |
| `call_participant_joined` | group members | someone joined |
| `call_participant_left` | group members | someone left |

A matching **FCM data push** goes out alongside `incoming_call` so a backgrounded or
killed app still rings. Payload is data-only (no `notification` block) with
`type: "incoming_call"`, `call_id`, `call_type`, `media`.

**Socket events and pushes are separate channels and do not mirror each other.** On a 1:1
reject the caller receives exactly one socket event, `call_rejected`; the push sent on the
same action carries `type: "call_ended"` with `end_reason: "rejected"`. A client listening
on both will see both, which is why de-duplicating on the first terminal signal is the
right approach.

---

## 4. Enums

| Field | Values |
|---|---|
| `status` | `ringing` · `active` · `ended` · `rejected` · `missed` · `cancelled` · `failed` |
| `end_reason` | `hung_up` · `missed` · `rejected` · `cancelled` · `timeout` · `failed` |
| `call_type` | `dm` · `group` |
| `media` | `audio` · `video` (video is `501` today) |
| participant `state` | `invited` · `ringing` · `joined` · `left` · `rejected` · `missed` |
| participant `role` | `caller` · `callee` |

---

## 5. Errors

Errors are **not** wrapped in the success envelope:

```json
{ "detail": "You are not a participant in this call." }
```

`422` is the exception — FastAPI's validation shape:

```json
{ "detail": [{ "type": "value_error", "loc": ["body"],
               "msg": "Value error, target_user_id is required for a dm call" }] }
```

| Code | Meaning | Verified example |
|---|---|---|
| 401 | missing or bad token | `"Not authenticated"` |
| 403 | not your call | `"You are not a participant in this call."` |
| 404 | no such call | `"Call not found."` |
| 409 | wrong state for this action | `"Call has already ended."` · `"Accept the call before requesting a token."` · `"Call is no longer ringing."` |
| 422 | payload failed validation | see above |
| 429 | too many call starts | `"Too many requests. Retry after 3600 seconds."` |
| 429 | out of call minutes | `"You have reached today's calling limit."` (per user) · `"Calling is temporarily unavailable."` (platform budget) |
| 501 | `"Video calling is not yet available."` | |

---

## 6. Timings and limits

| | |
|---|---|
| Ring timeout | **45 s**, then `missed` |
| Heartbeat interval | **30 s** (follow `next_heartbeat_in_seconds`) |
| Heartbeat timeout | **90 s** of silence → call torn down |
| Max call duration | **2 h** hard cap |
| Max group participants | **20** |
| Call starts | **10 per hour per user** |
| Stream token lifetime | **1 h** |

---

## 7. Client checklist

0. Register the device's FCM token with `POST /calls/devices` on sign-in and on every
   token refresh — an unregistered device never rings when backgrounded.
1. Start or accept a call, then join Stream with `stream.api_key`, `stream.token`,
   `stream.call_type` and `stream.call_id` (un-hyphenated).
2. Start a 30 s heartbeat as soon as the call is `active`; stop it when the call ends.
3. Listen for `call_ended` and leave the Stream session — do not rely on your own
   hang-up alone.
4. Handle `call_answered_elsewhere` by silencing the ringer on that device.
5. Refresh the Stream token before the hour is up on long calls.
6. Treat `409` as "the call moved on" and re-read `GET /calls/{id}` rather than retrying.
7. On app restart with a call still `active`: `GET /calls/{id}`, then `POST /calls/{id}/token`
   to rejoin. Works for caller and callee alike — do not call `/accept` again.

---

## 8. What is verified, and what is not

Captured live against production on 2026-09-21, so these are exact: every 1:1 endpoint
above, all response shapes, and the `401 / 403 / 404 / 409 / 422 / 429 / 501` bodies.
Stream token lifetime confirmed by decoding the JWT (`exp - iat = 3600`).

Corrections issued 2026-09-21 after frontend review — these paragraphs replace what the
earlier `audio_calling_contract.md` said: the caller *can* re-mint a token after a restart;
the in-chat call card has no `direction` field; a 1:1 reject emits `call_rejected` on the
socket and `call_ended` on the push.

**Not verified end to end — treat as read from the code, not observed:**

- **Group calls.** The request shape and the `group` / `participant_count` fields come
  from the schema and the group branch of the code. No group call has been placed
  against production.
- **Socket events.** Names and payloads are read from the emit sites in
  `app/modules/calling/`. No socket client was attached during testing.
- **FCM push.** The backend builds and sends it, but delivery to a handset is unproven —
  it needs a real device token
  (`python3 _migration/smoke_calling.py --fcm-token <token>`). Until someone runs that,
  assume ringing a backgrounded app is untested.
- **iOS VoIP / PushKit.** Not built. No APNs credentials are configured, so nothing can
  push to a `token_type: "voip"` row. Ringing a killed iPhone does not work today.
