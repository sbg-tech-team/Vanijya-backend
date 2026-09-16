# Audio Calling — Frontend Contract

> **Status:** backend implemented (`app/modules/calling/`), migration `446633e0fd8d`.
> Pending `STREAM_API_KEY` / `STREAM_API_SECRET` and FCM credentials before it can run.
> This document is the agreement between backend and frontend.
>
> **Provider:** Stream Video & Audio (getstream.io) — a new vendor dependency for this
> codebase; nothing else here uses Stream.

---

## 1. How it works in one paragraph

Stream carries the **audio**. Our backend owns **everything else**: who may call whom,
ringing, push notifications, call state, history and duration. The client never talks to
Stream's API directly to create or manage a call — it asks our backend, gets a short-lived
Stream token back, and uses that token only to join the media session.

```
  Caller                    Our Backend                 Callee
    │                            │                         │
    │── POST /calls ────────────►│                         │
    │                            │── FCM data push ───────►│  (app backgrounded)
    │                            │── socket incoming_call ─►│  (app foreground)
    │◄── stream token + call_id ─│                         │
    │                            │◄── POST /calls/{id}/accept
    │◄── socket call_accepted ───│──── stream token ──────►│
    │                            │                         │
    │═══════ audio flows through Stream, not us ══════════►│
    │                            │                         │
    │── POST /calls/{id}/end ───►│                         │
    │                            │── socket call_ended ───►│
```

---

## 2. Decisions taken

| Decision | Choice | Why |
|---|---|---|
| Ringing | **Our backend** (FCM + Socket.IO), not Stream's ring feature | Requested — keeps control in our architecture |
| Duration source | **Our timestamps** (`accept` → `end`), not Stream webhooks | No public webhook endpoint or signature verification needed |
| Stale calls | APScheduler reaper every 2 min | Both clients can die without sending `end` |
| Call card in chat | Yes — new `message_type: "call"` | Matches WhatsApp behaviour; reuses existing `messages` table |
| Group cap | **20 participants** (`MAX_CALL_PARTICIPANTS`, configurable) | Audio-only; tune once real usage is known |
| Ring timeout | **45 seconds**, then auto-`missed` | Standard |
| Permission gate | **Block only** — no relationship requirement | Requested: "anyone can call anyone" |
| Video | Not now. `media` field present from day one so enabling it is a flag | Requested |

### Open item — spam risk

"Anyone can call anyone" means a brand-new account can cold-call any user on the platform.
There is an unused `RateLimiter` in `app/core/rate_limiter.py` — the backend will apply it to
`POST /calls` (proposed: **10 call initiations per user per hour**). Frontend must handle
**429** on initiate. Tell us if you want a different limit.

---

## 3. Conventions

- **Base URL prefix:** `/calls`
- **Auth:** `Authorization: Bearer <access_token>` on every endpoint. Identity is always taken
  from the token — never send `user_id` in a body or path.
- **Envelope:** every success response is wrapped exactly like the rest of the API:

```json
{ "success": true, "message": "Human readable", "data": { } }
```

  Everything documented below under "Response" is the contents of `data`.
- **Errors:** FastAPI standard — `{ "detail": "message" }` with the HTTP status.
- **Timestamps:** ISO-8601 UTC, e.g. `"2026-09-15T11:19:04Z"`.
- **IDs:** `call_id` is our UUID. `stream_call_id` is Stream's identifier — pass it to the
  Stream SDK verbatim, never parse it.

---

## 4. Endpoints

### 4.1 `POST /calls` — start a call

**Request (1:1):**
```json
{
  "call_type": "dm",
  "target_user_id": "8f14e45f-ceea-467a-9f0a-3b2c1d4e5f60",
  "media": "audio"
}
```

**Request (group):**
```json
{
  "call_type": "group",
  "group_id": "3b2c1d4e-5f60-4a7b-8c9d-0e1f2a3b4c5d",
  "media": "audio"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `call_type` | `"dm"` \| `"group"` | yes | |
| `target_user_id` | UUID | dm only | The person being called |
| `group_id` | UUID | group only | Caller must be a member |
| `media` | `"audio"` \| `"video"` | no, default `"audio"` | `"video"` returns **501** until video ships |

**Response `201`:**
```json
{
  "call_id": "c1a2b3c4-d5e6-47f8-a9b0-c1d2e3f4a5b6",
  "call_type": "dm",
  "media": "audio",
  "status": "ringing",
  "created_at": "2026-09-15T11:19:04Z",
  "ring_timeout_seconds": 45,
  "stream": {
    "api_key": "abc123xyz",
    "token": "eyJhbGciOiJIUzI1NiIs...",
    "user_id": "8f14e45f-ceea-467a-9f0a-3b2c1d4e5f60",
    "call_type": "default",
    "call_id": "c1a2b3c4d5e647f8a9b0c1d2e3f4a5b6"
  },
  "participants": [
    {
      "user_id": "8f14e45f-ceea-467a-9f0a-3b2c1d4e5f60",
      "profile_id": 42,
      "name": "Ramesh Patel",
      "avatar_url": "https://.../avatar.jpg",
      "role": "caller",
      "state": "joined"
    },
    {
      "user_id": "9a25f56g-dffb-578b-a01b-4c3d2e5f6a71",
      "profile_id": 87,
      "name": "Sunita Shah",
      "avatar_url": null,
      "role": "callee",
      "state": "ringing"
    }
  ]
}
```

> **On `stream`:** join the Stream call with `stream.call_type` + `stream.call_id`. The token is
> valid **1 hour**. For calls that outlive it, see §4.7.
>
> **On `avatar_url`:** may be `null`. Render initials from `name` as fallback. Avatars come from
> our `profile` table, not from Stream.

**Errors:**

| Status | `detail` | When |
|---|---|---|
| 403 | `"You cannot call this user."` | Either party has blocked the other |
| 403 | `"You are not a member of this group."` | Group call, caller not a member |
| 404 | `"User not found."` / `"Group not found."` | |
| 409 | `"You are already in a call."` | Caller has an active/ringing call |
| 409 | `"User is already in a call."` | Callee is busy (1:1 only) |
| 422 | validation error | Bad payload |
| 429 | `"Too many requests. Retry after 3600 seconds."` | Rate limit |
| 501 | `"Video calling is not yet available."` | `media: "video"` |
| 503 | `"Calling is temporarily unavailable."` | Stream unreachable |

---

### 4.2 `POST /calls/{call_id}/accept`

Body: none.

**Response `200`:**
```json
{
  "call_id": "c1a2b3c4-d5e6-47f8-a9b0-c1d2e3f4a5b6",
  "status": "active",
  "started_at": "2026-09-15T11:19:22Z",
  "stream": {
    "api_key": "abc123xyz",
    "token": "eyJhbGciOiJIUzI1NiIs...",
    "user_id": "9a25f56g-dffb-578b-a01b-4c3d2e5f6a71",
    "call_type": "default",
    "call_id": "c1a2b3c4d5e647f8a9b0c1d2e3f4a5b6"
  },
  "participants": [ ... ]
}
```

`started_at` is set on the **first** accept and never moves. Duration is measured from it.

**Errors:** `403` blocked (re-checked at accept), `404` unknown call, `409 "Call is no longer
ringing."` (already ended / rejected / timed out), `409 "Call is full."` (group at cap).

---

### 4.3 `POST /calls/{call_id}/reject`

Body: none. **Response `200`:**
```json
{ "call_id": "...", "status": "rejected" }
```

1:1 — call ends immediately, caller gets `call_rejected`.
Group — only *your* participant row becomes `rejected`; the call continues for everyone else.

**Errors:** `404`, `409 "Call is no longer ringing."`

---

### 4.4 `POST /calls/{call_id}/end`

Hang up. Any participant may call this.

**Response `200`:**
```json
{
  "call_id": "...",
  "status": "ended",
  "started_at": "2026-09-15T11:19:22Z",
  "ended_at": "2026-09-15T11:23:47Z",
  "duration_seconds": 265,
  "end_reason": "hung_up"
}
```

`end_reason`: `hung_up` | `missed` | `rejected` | `cancelled` | `timeout` | `failed`

1:1 — ends the call for both.
Group — you leave; the call ends only when the **last** participant leaves.

If the call never reached `active`, `duration_seconds` is `0` and `started_at` is `null`.

**Errors:** `404`, `409 "Call has already ended."` — treat 409 as success and tear down your UI.

---

### 4.5 `GET /calls/{call_id}` — poll state

Use on app resume, or if you suspect a missed socket event. Not for polling in a loop.

**Response `200`:** same shape as §4.1 minus `stream` (no token is issued here).

---

### 4.6 `GET /calls` — call history

Query: `limit` (default 20, max 50), `cursor` (opaque, from `next_cursor`),
`call_type` (optional filter).

**Response `200`:**
```json
{
  "calls": [
    {
      "call_id": "...",
      "call_type": "dm",
      "media": "audio",
      "status": "ended",
      "direction": "outgoing",
      "end_reason": "hung_up",
      "created_at": "2026-09-15T11:19:04Z",
      "started_at": "2026-09-15T11:19:22Z",
      "ended_at": "2026-09-15T11:23:47Z",
      "duration_seconds": 265,
      "counterparty": {
        "user_id": "...", "profile_id": 87,
        "name": "Sunita Shah", "avatar_url": null
      },
      "group": null
    },
    {
      "call_id": "...",
      "call_type": "group",
      "status": "ended",
      "direction": "incoming",
      "end_reason": "missed",
      "duration_seconds": 0,
      "counterparty": null,
      "group": { "group_id": "...", "name": "Gujarat Cotton Traders", "image_url": "https://..." },
      "participant_count": 4
    }
  ],
  "next_cursor": "eyJpZCI6..."
}
```

`direction` is `"outgoing"` if you initiated, else `"incoming"`.
For `call_type: "dm"`, `counterparty` is the other person and `group` is `null`. For
`"group"`, the reverse.

---

### 4.7 `POST /calls/{call_id}/heartbeat` — liveness ping ⚠️ REQUIRED

**Send every 30 seconds for the entire time you are in a call.** This is not optional.

When the pings stop, the backend concludes every client is gone — force-quit, crashed,
or out of battery — and ends the call within 90 seconds. Without it, the only evidence
a call is over is your client politely saying so, which is exactly what fails when the
user swipes the app away mid-call. That call would otherwise bill until the two-hour cap
and leave both users unable to start another one.

Body: none. **Response `200`:**
```json
{ "call_id": "...", "status": "active", "next_heartbeat_in_seconds": 30 }
```

**Errors:** `403` not a participant, `404` unknown call,
`409 "Call has already ended."` — **stop the media session immediately.** A 409 here is
your fallback teardown signal when both the socket event and the push were missed.

---

### 4.8 `POST /calls/{call_id}/token` — refresh Stream token

Stream tokens last 1 hour. For longer calls, refresh **before** expiry (recommended: at 50 min,
or when the SDK raises a token-expiry event).

**Response `200`:**
```json
{ "token": "eyJhbGciOiJIUzI1NiIs...", "expires_at": "2026-09-15T12:19:04Z" }
```

**Errors:** `403` not a participant; `409 "Accept the call before requesting a token."`
— you must be joined, this endpoint cannot be used to skip `/accept`; `409` call already
ended; `409 "Call has reached its maximum duration."` — the two-hour cap, tear down and
do not retry.

---

## 5. Realtime events (Socket.IO)

Same connection you already use for chat — `app/modules/chat/presentation/connection_manager.py`.
No new socket, no new auth. Events are delivered to your existing `user:{user_id}` room.

| Event | Sent to | Payload |
|---|---|---|
| `incoming_call` | callee(s) | full call object (as §4.1, **without** `stream`) |
| `call_accepted` | caller | `{ call_id, accepted_by: user_id, started_at }` |
| `call_rejected` | caller | `{ call_id, rejected_by: user_id }` |
| `call_ended` | all participants | `{ call_id, ended_by, ended_at, duration_seconds, end_reason }` |
| `call_participant_joined` | group participants | `{ call_id, participant: {...} }` |
| `call_participant_left` | group participants | `{ call_id, user_id }` |
| `call_cancelled` | callee(s) | `{ call_id }` — caller hung up before answer |

> ⚠️ **Single-worker constraint.** Socket.IO state is in-process (documented in
> `connection_manager.py`). These events only reach sockets on the same worker. Production runs
> one worker, so this is fine today — but **never rely on socket events alone**. FCM is the
> reliable path; sockets are the fast path.

---

## 6. Push notification (FCM)

Sent to every device token of the callee. **Data-only message** — no `notification` block — so
the app can render its own full-screen incoming-call UI rather than a system banner.

```json
{
  "data": {
    "type": "incoming_call",
    "call_id": "c1a2b3c4-d5e6-47f8-a9b0-c1d2e3f4a5b6",
    "call_type": "dm",
    "media": "audio",
    "caller_user_id": "8f14e45f-ceea-467a-9f0a-3b2c1d4e5f60",
    "caller_name": "Ramesh Patel",
    "caller_avatar_url": "https://.../avatar.jpg",
    "group_id": null,
    "group_name": null,
    "created_at": "2026-09-15T11:19:04Z",
    "ring_timeout_seconds": 45
  },
  "android": { "priority": "high" },
  "apns": { "headers": { "apns-priority": "10", "apns-push-type": "voip" } }
}
```

A matching `call_cancelled` / `call_ended` data-push is sent so the device can dismiss the
incoming-call screen if the caller gives up.

**Frontend requirements:**

1. `PATCH /profile/user/fcm-token` **already exists** — keep calling it on every app start and on
   token rotation. Backend currently stores exactly one token per user; if you need multi-device,
   say so now, because that changes the table.
2. Android: full-screen intent + `ConnectionService` for the native call UI.
3. iOS: **PushKit + CallKit**. Apple requires a VoIP push to be reported to CallKit immediately
   or the app gets killed. This is why the payload is data-only.

---

## 7. Mute and speaker — client-side only

These are **not** backend endpoints. They are Stream SDK / OS calls:

| Feature | Call | Notes |
|---|---|---|
| Mute self | `call.microphone.disable()` / `.enable()` | Stream propagates your muted state to other participants automatically |
| Read others' mute | `participant.audioEnabled` from SDK participant state | Live from the SDK, not from our API |
| Speaker on/off | OS audio route (earpiece ↔ loudspeaker) | Purely local. Stream is not involved. Android: `AudioManager`. iOS: `AVAudioSession.overrideOutputAudioPort` |

Our backend never knows or stores mute/speaker state. Don't send us these.

---

## 8. In-chat call card

Every finished call writes one message into the conversation, so call history appears inline in
chat. It arrives through your **existing** `new_message` / `new_group_message` socket event and
the existing `GET /chat/conversations/{id}/messages` endpoint — no new plumbing.

New `message_type: "call"`, joining `text` / `deal` / `post` / `news_article`:

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
    "duration_seconds": 265,
    "direction": "outgoing"
  },
  "sent_at": "2026-09-15T11:23:47Z"
}
```

Render like WhatsApp: ↗ outgoing / ↙ incoming, red for `missed`, duration when `> 0`.

---

## 9. Call states

```
                    ┌──────────┐
   POST /calls ────►│ ringing  │
                    └────┬─────┘
          accept ────────┼──────── reject ──────► rejected
                         │
                    ┌────▼─────┐   45s no answer ─► missed
                    │  active  │   caller hangs up ─► cancelled
                    └────┬─────┘
                         │ end / last participant leaves
                    ┌────▼─────┐
                    │  ended   │
                    └──────────┘
```

| Status | Meaning |
|---|---|
| `ringing` | Created, waiting for an answer |
| `active` | At least two participants joined |
| `ended` | Finished normally |
| `rejected` | Callee declined (1:1) |
| `missed` | Ring timeout expired |
| `cancelled` | Caller hung up before answer |
| `failed` | Stream error / reaped stale call |

**Terminal states are final.** Once a call is not `ringing` or `active`, every mutating endpoint
returns `409`.

---

## 10. Frontend checklist

1. On login, ensure the Socket.IO connection is live (you already do this for chat) and
   `PATCH /profile/user/fcm-token` has been called.
2. **Outgoing:** `POST /calls` → show ringing UI → join Stream with the returned token →
   wait for `call_accepted`.
3. **Incoming (foreground):** `incoming_call` socket event → show UI.
   **Incoming (background):** FCM data push → CallKit / ConnectionService → show UI.
   *De-duplicate by `call_id`* — you will often receive both.
4. **Accept:** `POST /calls/{id}/accept` → join Stream with the returned token.
5. **Mute / speaker:** SDK and OS only. No API calls (§7).
6. **Duration:** for the live on-screen timer, count up from `started_at` locally. For history,
   use the server's `duration_seconds` — it is the source of truth.
7. **End:** `POST /calls/{id}/end`, then leave the Stream call. Treat `409` as success.
9. **Always** handle `call_ended` arriving unprompted — the other side may hang up, or the
   reaper may kill a stale call.

---

## 11. Backend work this implies

Not frontend concerns, listed so both sides see the full scope:

- `app/modules/calling/` — standard `domain` / `data` / `application` / `presentation` layout
- Tables: `calls`, `call_participants` — **with indexes** (the post module has none; not repeating that)
- `STREAM_API_KEY`, `STREAM_API_SECRET` added to `app/core/config.py`
  — ⚠️ these **must** be declared on the `Settings` class. Reading an undeclared setting raises
  `AttributeError` at the call site, which is exactly how the news pipeline silently died.
- `stream-chat` / Stream server SDK added to `requirements.txt`
- **FCM sender** — genuinely new. `firebase_admin` is installed but only verifies OTP tokens
  today; nothing in the codebase sends a push.
- Block enforcement via the existing-but-unused `either_blocked()` in the safety repo
- Rate limiting via the existing-but-unused `RateLimiter`
- APScheduler jobs: ring-timeout sweeper (30 s), stale-call reaper (2 min)
- New `message_type="call"` in the chat message builder

---

## 12. Cost guardrails — what the backend enforces

Stream bills **participant-minutes** (participants × wall-clock duration), so a call
that never ends bills forever. Frontend does not implement any of this, but two items
surface as HTTP responses you must handle.

**Layers, in order of what survives what:**

| # | Guardrail | Enforced by | Survives a backend outage? |
|---|---|---|---|
| 1 | `max_duration_seconds` (2 h) sent at call creation | **Stream** | **Yes** |
| 2 | Session ends 30 s after the last participant leaves | **Stream** | Yes, once clients drop |
| 3 | Ring timeout 45 s → `missed` | Our backend | No |
| 4 | **Heartbeat timeout 90 s → `ended`** | Our backend | No |
| 5 | Solo-participant timeout 2 min → `ended` | Our backend | No |
| 6 | Max-duration sweep 2 h → `ended` | Our backend | No |
| 7 | Provider-termination retry (5 min) | Our backend | No |
| 8 | Stale reaper 4 h → `failed` | Our backend | No |
| 9 | Per-user budget: 600 participant-min/day | Our backend | No |
| 10 | Platform budget: 300,000 participant-min/month | Our backend | No |

**Heartbeats are tracked per participant, not per call.** Each client's ping marks
*that person* present. A call with two people where one device dies is detected as solo
within 90 s even though the survivor is still pinging happily — a call-level heartbeat
could not tell those two situations apart.

**Layer 4 is the one that answers "what if the user just closes the app".** Heartbeats
stop, and 90 seconds later the call is gone. It depends on the client actually sending
them — see §4.7 — which is why that endpoint is required rather than optional.

**Layer 5 catches the other common case.** If B's phone dies mid-call and A's phone is
in a pocket, A's client has no idea anything is wrong and never sends `end`. Two minutes
alone and the backend ends it — there was nobody on the other side.

A call ended by any sweep still **writes its chat card and emits `call_ended`**, so a
missed call appears in the conversation and the caller's ringing screen clears.

**Every one of those paths also terminates the session on Stream**, not just in our
database. Ending a call locally does not stop the meter.

### What the frontend must handle

- **429 on `POST /calls`** with `"You have reached today's calling limit."` — that user
  has burned their daily budget. Show it as a limit, not an error.
- **429 with `"Calling is temporarily unavailable."`** — the platform budget is spent.
  Same UI as 503.
- **`call_ended` arriving with `end_reason: "timeout"`** — the backend ended the call
  because it hit a cap or went solo. Tear down normally; this is not a crash.

### Why the defaults are what they are

At $0.30 per 1,000 audio participant-minutes, the 300,000/month platform ceiling caps
spend at roughly **$90/month**, which sits inside Stream's $100 free credit. A forgotten
1:1 call running a full day would otherwise cost $0.86; a forgotten 20-person group call
would cost $8.64. The caps make the worst case bounded rather than open-ended.

Both budgets are configurable via `CALLS_PER_USER_DAILY_MINUTES` and
`CALLS_PLATFORM_MONTHLY_MINUTES`. Raise them deliberately.

---

## 13. Not in scope

- Video (contract is shaped for it; `media: "video"` returns `501`)
- Call recording
- Screen sharing
- Dropping a live call when a block happens mid-call
- Multi-device ringing (one FCM token per user today — flag it if you need more)
- Call quality / network stats reporting
