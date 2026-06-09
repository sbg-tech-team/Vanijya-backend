# Vanijyaa Chat — End-to-End REST Test Runbook

Drive every step below in Postman (or `curl`). Every action is a normal HTTP call;
Socket.IO only pushes events in the background, so run `socket_listener.py` alongside
this to watch the real-time pushes land.

**Base URL:** `https://vanijyaa-backend.onrender.com`

---

## Test users

| Label | Name | Role in flow |
|---|---|---|
| **A** | aadya | Initiator |
| **S** | sanket | Receiver |

`user_id` values come from the dev-token response — see token setup below.

### Getting tokens (local dev)

Requires `DEBUG=true` in your `.env`. Tokens never expire this way.

```
GET {{base_url}}/auth/dev-token?name=aadya
GET {{base_url}}/auth/dev-token?name=sanket
```

Each returns `{ "access_token": "...", "user_id": "...", "profile_id": ..., "name": "..." }`.

Paste the `access_token` values into Postman as `aadya_token` / `sanket_token`.
Note the `user_id` for each — you'll need them in the request bodies below.

### Recommended Postman setup

Create an environment with these variables:

| Variable | Value |
|---|---|
| `base_url` | `http://localhost:8000` (local) or `https://vanijyaa-backend.onrender.com` (Render) |
| `aadya_token` | *(from dev-token above)* |
| `sanket_token` | *(from dev-token above)* |
| `aadya_id` | *(user_id from aadya dev-token response)* |
| `sanket_id` | *(user_id from sanket dev-token response)* |
| `conv_id` | *(auto-filled in Step 1)* |
| `group_id` | *(auto-filled in Step 7)* |

`conv_id` and `group_id` are the only values generated at runtime; the snippets in Steps 1 and 7 auto-save them.

---

## Phase 1 — DM request & accept

### Step 1 — A starts the conversation (creates a `requested` DM)

```
POST {{base_url}}/chat/conversations
Authorization: Bearer {{aadya_token}}
Content-Type: application/json
```
```json
{
  "participant_id": "{{sanket_id}}",
  "first_message": "Hi Sanket, interested in 200 MT Basmati?"
}
```
**Expect `201`** → `{ "conversation": {...}, "message": {...}, "created": true }`, status `requested`.
**Fires:** `new_message` → `user:{sanket_id}` (Sanket's listener prints it).

Postman → *Scripts → Post-response*, auto-save the conversation id:
```javascript
pm.environment.set("conv_id", pm.response.json().conversation.id);
```

---

### Step 2 — S sees it in their conversation list

```
GET {{base_url}}/chat/conversations
Authorization: Bearer {{sanket_token}}
```
**Expect `200`** → array containing the conversation with `status: "requested"`. This is the
"see it in my requests" view.

> Send rule check (optional): if **S** tries `POST .../{{conv_id}}/messages` now, it returns
> `403` — only the initiator can send while status is `requested`. Expected behaviour.

---

### Step 3 — S accepts the request

```
POST {{base_url}}/chat/conversations/{{conv_id}}/accept
Authorization: Bearer {{sanket_token}}
```
**Expect `200`** → updated conversation, status now `active`. Both can send freely.
**Fires:** `conversation_accepted` → `user:{aadya_id}` (Aadya's listener prints it).

---

### Step 4 — S replies (now allowed)

```
POST {{base_url}}/chat/conversations/{{conv_id}}/messages
Authorization: Bearer {{sanket_token}}
Content-Type: application/json
```
```json
{ "body": "Yes, tell me the price and grade.", "message_type": "text" }
```
**Expect `201`** → `MessageEntity`.
**Fires:** `new_message` → `user:{aadya_id}` (Aadya's listener prints it).

---

### Step 5 — A replies back

```
POST {{base_url}}/chat/conversations/{{conv_id}}/messages
Authorization: Bearer {{aadya_token}}
Content-Type: application/json
```
```json
{ "body": "Grade A, long grain. ₹42,000/MT negotiable.", "message_type": "text" }
```
**Expect `201`. Fires:** `new_message` → `user:{sanket_id}`.

---

### Step 6 — Verify the DM history

```
GET {{base_url}}/chat/conversations/{{conv_id}}/messages?limit=50
Authorization: Bearer {{aadya_token}}
```
**Expect `200`** → array of all messages, newest first. This proves persistence independent of the push.

---

## Phase 2 — Group

> **Verification gate:** creating a group needs the creator to be **KYC + KYB verified**.
> If Aadya is not fully verified, `POST /api/v1/groups/` returns `403` — create the group
> with a verified account instead (joining has no verification requirement).

### Step 7 — A creates a public group

```
POST {{base_url}}/api/v1/groups/
Authorization: Bearer {{aadya_token}}
Content-Type: application/json
```
```json
{
  "name": "Rice Test Group",
  "description": "Test group for end-to-end chat flow.",
  "commodity": ["rice"],
  "target_roles": ["trader", "exporter"],
  "accessibility": "public",
  "posting_perm": "all_members",
  "chat_perm": "all_members"
}
```
**Expect `201`** → `GroupOut`. Creator is auto-added as `admin`.

Postman → *Scripts → Post-response*, auto-save the group id:
```javascript
// if your create response is wrapped in {data}, use pm.response.json().data.id
pm.environment.set("group_id", pm.response.json().id);
```

---

### Step 8 — S joins the group (instant for public)

```
POST {{base_url}}/api/v1/groups/{{group_id}}/join
Authorization: Bearer {{sanket_token}}
```
**Expect `201`** → both are now members.

> For a private group, this instead creates a join request. Aadya (admin) would then list
> `GET /api/v1/groups/{{group_id}}/join-requests` and approve via
> `POST /api/v1/groups/{{group_id}}/join-requests/{request_id}/approve`.

**Now set `GROUP_ID` in `socket_listener.py` and re-run it**, so both sockets emit
`join_group` and start receiving group pushes.

---

### Step 9 — A sends a group message

```
POST {{base_url}}/chat/groups/{{group_id}}/messages
Authorization: Bearer {{aadya_token}}
Content-Type: application/json
```
```json
{ "body": "Welcome — anyone selling rice this week?", "message_type": "text" }
```
**Expect `201`. Fires:** `new_group_message` → `group:{{group_id}}` (both listeners print it).

---

### Step 10 — S replies in the group

```
POST {{base_url}}/chat/groups/{{group_id}}/messages
Authorization: Bearer {{sanket_token}}
Content-Type: application/json
```
```json
{ "body": "I have 300 MT available.", "message_type": "text" }
```
**Expect `201`. Fires:** `new_group_message` → `group:{{group_id}}`.

---

### Step 11 — Verify group history

```
GET {{base_url}}/chat/groups/{{group_id}}/messages?limit=50
Authorization: Bearer {{sanket_token}}
```
**Expect `200`** → all group messages, newest first.

---

## Phase 3 — Deals

### Step 12 — A posts a deal into the group

```
POST {{base_url}}/chat/groups/{{group_id}}/deals
Authorization: Bearer {{aadya_token}}
Content-Type: application/json
```
```json
{
  "commodity_id": 1,
  "title": "Fresh Basmati Rice — Bulk Available",
  "caption": "Grade A Basmati, 500 MT available immediately.",
  "grain_type": "raw",
  "grain_size": "long",
  "commodity_quantity": 500,
  "quantity_unit": "MT",
  "commodity_price": 42000,
  "price_type": "negotiable",
  "publish_to_feed": false
}
```
**Expect `201`** → `GroupDealResponse`. **Fires:** `new_group_deal` → `group:{{group_id}}`.

---

### Step 13 — A posts a personal deal into the DM

> The conversation must be `active` (it is, after Step 3).

```
POST {{base_url}}/chat/conversations/{{conv_id}}/deals
Authorization: Bearer {{aadya_token}}
Content-Type: application/json
```
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
  "price_type": "negotiable"
}
```
**Expect `201`** → `MessageEntity` with `message_type: "deal"`.
**Fires:** `new_message` → `user:4146b589-154d-4c98-bfda-60282022d85c`.

---

## Socket events reference

| Step | Endpoint | Event | Room | Who receives |
|---|---|---|---|---|
| 1 | `POST /chat/conversations` | `new_message` | `user:{sanket_id}` | S |
| 3 | `POST .../{conv_id}/accept` | `conversation_accepted` | `user:{aadya_id}` | A |
| 4 | `POST .../{conv_id}/messages` (S) | `new_message` | `user:{aadya_id}` | A |
| 5 | `POST .../{conv_id}/messages` (A) | `new_message` | `user:{sanket_id}` | S |
| 9,10 | `POST /chat/groups/{group_id}/messages` | `new_group_message` | `group:{group_id}` | all members in room |
| 12 | `POST /chat/groups/{group_id}/deals` | `new_group_deal` | `group:{group_id}` | all members in room |
| 13 | `POST /chat/conversations/{conv_id}/deals` | `new_message` | `user:{sanket_id}` | S |

## Gotchas

- **Cold start:** the Render free instance spins down after ~15 min idle; the first call after idle can take 30–60s.
- **Token expiry (local):** use `GET /auth/dev-token?name=<name>` (needs `DEBUG=true`) — tokens never expire this way.
- **Token expiry (Render):** if you get `401`, re-fetch from the login response and update your Postman variables.
- **Group rooms:** group pushes only arrive at a socket that has emitted `join_group` — set `GROUP_ID` in `socket_listner.py` and re-run after Step 8. The server silently ignores `join_group` if the user is not a DB member.
- **DM rooms:** no `join_group` needed — the server auto-joins `user:{user_id}` on connect, so DM pushes work immediately.
- **`conversation_accepted` / `conversation_declined`:** only the conversation initiator (A) receives these — the receiver (S) who called accept/decline doesn't get a push back.