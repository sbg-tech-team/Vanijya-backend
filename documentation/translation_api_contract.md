# Translation API — Frontend Contract

> Backend implemented in `app/modules/translation/`, wired into the chat router.
> Migrations `69723a8b6af7` (preferences + rolling context) and `a1f7c93b204e`
> (`message_translations`). Engine is Gemini.

Two modes:

- **Single tap** — the reader taps one message and gets it translated. Works in DMs and
  in groups.
- **Continuous** — the reader turns it on for one DM, and every incoming message in that
  conversation is translated for them automatically. **DMs only.**

Translations are stored per `(message_id, target_lang)`, not per reader: two people
reading the same group in the same language cost one engine call, not two.

---

## 1. Endpoints

### POST /chat/messages/{message_id}/translate — single tap

```json
{ "target_lang": "hi" }
```

`target_lang` is optional. When omitted the backend resolves it: the reader's
per-conversation preference, then their app-wide default, then auto (detect the source
language; translate to Hindi if it is already English, otherwise to English).

**200**

```json
{ "translated_text": "नमस्ते", "target_lang": "hi", "used_cache": false }
```

Works for **group messages as well as DMs** — pass any message id the reader can see.

| Code | When | Body |
|---|---|---|
| 403 | reader is not in that DM or group | `{"detail": "You do not have access to this message."}` |
| 404 | no such message, deleted, or no text body | `{"detail": "Message not found or has no text body."}` |
| 429 | **60 translations per hour per user** | `{"detail": "Too many requests. Retry after 3600 seconds."}` |
| 503 | engine has no API key or is unreachable | `{"detail": ...}` |

The 403 is enforced before the engine is called, so a rejected request costs nothing and
counts nothing.

### GET /chat/conversations/{conv_id}/continuous-translation — read the setting

**200**

```json
{ "conversation_id": "…", "target_lang": "hi", "continuous_enabled": true }
```

Returns `continuous_enabled: false` and `target_lang: null` when it has never been set.
Call this when opening a thread rather than trusting a cached toggle response — the
setting is server-side and survives reinstalls.

### POST /chat/conversations/{conv_id}/continuous-translation — change the setting

```json
{ "enabled": true, "target_lang": "hi" }
```

`target_lang` is optional; when omitted it is resolved once at opt-in and stored, so
later messages do not re-run the resolution chain. **200**, same shape as the GET.

`400 {"detail": "Continuous translation is only available for direct messages."}` for a
group.

---

## 2. Reading translations back

`GET /chat/conversations/{conv_id}/messages` returns two extra fields on every message:

```json
{
  "id": "…",
  "body": "नमस्ते",
  "translated_text": "hello",
  "target_lang": "en",
  "sent_at": "2026-09-21T11:23:47Z"
}
```

Both are `null` unless **all** of the following hold: the reader has continuous
translation on for this conversation, a target language is resolved, and a stored
translation exists for that message in that language. Fall back to `body` whenever
`translated_text` is null.

This is what makes scroll-back, reopening a thread, reconnecting after a dropped socket,
and messages received while offline all show translated text — the live
`message_translated` socket event alone cannot do any of those.

Fetching them costs one extra query for the whole page, and nothing at all when
continuous is off.

**Groups:** `translated_text` is always null on `GET /chat/groups/{id}/messages`, because
continuous mode does not exist for groups. Use single tap and hold the result client-side.

---

## 3. Socket event

| Event | Sent to | When |
|---|---|---|
| `message_translated` | the reader | a continuous-mode translation finished |

```json
{ "message_id": "…", "translated_text": "hello", "target_lang": "en" }
```

It is a latency optimisation, not the source of truth. Everything it carries is also
readable from `GET .../messages`, so a client that misses the event recovers on the next
fetch. Do not build state that depends on having received it.

---

## 4. Limits

| | |
|---|---|
| Single-tap translations | **60 per hour per user** |
| Continuous mode | DMs only, no per-message limit |
| Storage | per `(message_id, target_lang)`, deleted with the message |

Continuous mode is deliberately **not** rate limited: it is driven by incoming messages
rather than by the client, so the ceiling is the conversation's own message rate.

---

## 5. What is verified, and what is not

**Verified:** the use cases are unit-tested (`tests/test_translation.py`, 31 tests)
including the 403 on a non-member and that a rejected request never reaches the engine.
The `message_translations` migration has been replayed onto an empty database and passes
the ORM/migration drift check.

**Not verified end to end:** no live request has been made against production with a real
Gemini key, so response latency and the engine's behaviour on long messages are unmeasured.
`TRANSLATION_GEMINI_MODEL` is not set on Render and falls back to its default.
