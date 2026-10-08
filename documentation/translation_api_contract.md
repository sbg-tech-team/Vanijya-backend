# Translation Module — Frontend Contract

The full contract for translation in the app: language settings, translating posts / comments / news, and translating chat messages. Covers every endpoint, the exact request and response shapes, error codes, limits, and the UI flows to build.

> **Availability**
> - **Chat translation** (§6): live.
> - **Language preference and post / comment / news translation** (§4, §5): merged to `main` on 2026-09-28 (`79e1bdd`). Live once that deploy has gone green in GitHub Actions. Shapes below are final unless this document changes.

---

## 1. What exists

| Need | Endpoint | Section |
|---|---|---|
| Read / save the user's translation language | `GET` / `PUT /translate/preference` | §4 |
| Translate posts, comments, news (on tap) | `POST /translate/content` | §5 |
| Translate one chat message (on tap) | `POST /chat/messages/{message_id}/translate` | §6.1 |
| Auto-translate every incoming DM message | `GET` / `POST /chat/conversations/{conv_id}/continuous-translation` | §6.2 |
| Show stored chat translations on scroll-back | `translated_text` on `GET /chat/conversations/{conv_id}/messages` | §6.3 |
| Live chat translation push | socket event `message_translated` | §6.4 |

**Nothing is translated unless the user asks.** Feed, post, comment and news responses are unchanged and always carry the original text. A translation is shown **next to** the original, never instead of it.

---

## 2. Conventions

### Authentication
Every endpoint requires the access token:

```
Authorization: Bearer <access_token>
```

`401 {"detail": "Access token has expired"}` / `"Invalid access token"` → refresh the token and retry.

### Response envelope — different from posts and news
Translation endpoints return the payload **directly**, not wrapped in `{success, message, data}`:

```json
{ "lang": "hi", "items": [ ... ] }
```

Errors are FastAPI's standard shape:

```json
{ "detail": "Human-readable reason" }
```

`422` validation errors carry a list in `detail`:

```json
{ "detail": [ { "loc": ["body", "items"], "msg": "List should have at least 1 item after validation", "type": "too_short" } ] }
```

### Header sent on every request

```
X-App-Language: hi
```

The language the app UI is currently in. Send it on **every** request, from app start. It is how the backend knows the user runs the app in, say, Gujarati. Missing or unknown values are ignored, never an error.

---

## 3. Languages

| Code | Language | Script |
|---|---|---|
| `en` | English | Latin |
| `hi` | Hindi | Devanagari |
| `mr` | Marathi | Devanagari |
| `gu` | Gujarati | Gujarati |
| `pa` | Punjabi | Gurmukhi |
| `bn` | Bengali | Bengali |
| `ta` | Tamil | Tamil |
| `te` | Telugu | Telugu |
| `kn` | Kannada | Kannada |
| `ml` | Malayalam | Malayalam |
| `ur` | Urdu | Arabic |

- Codes are ISO 639-1. The backend also accepts `hi-IN`, `HI`, `hi_IN`, and always **returns the bare code** (`hi`).
- `GET /translate/preference` returns this list as `supported`, so the picker can be built from the API instead of hard-coded.
- Which languages are offered at launch is still to be decided. Build the picker from `supported`.

### Which language a translation goes into

**Posts, comments, news** (`POST /translate/content`), first match wins:

1. `target_lang` in the request body
2. `X-App-Language`, **if it is not English**
3. the user's saved preference (`PUT /translate/preference`)
4. none of these → **`409 language_required`**: show the language picker (§7.2)

**Chat** (`POST /chat/messages/{id}/translate`) resolves differently: body `target_lang`, then this conversation's continuous setting, then the saved preference, then an automatic fallback (English → Hindi, anything else → English). Chat does **not** read `X-App-Language`.

> **Recommendation:** compute one *reading language* in the app with the rule for posts above (app language if not English, else saved preference), and pass it explicitly as `target_lang` to the chat endpoints too. Then chat and posts always agree.

---

## 4. Language preference

The language to translate into when the app itself is in English. One setting drives both content and chat.

### `GET /translate/preference`

**200**

```ts
{
  target_lang: string | null          // null = never set
  supported: Record<string, string>   // { "en": "English", "hi": "Hindi (Devanagari script)", ... }
}
```

### `PUT /translate/preference`

```json
{ "target_lang": "mr" }
```

**200**: same shape as the GET, with the saved value.

| Code | When |
|---|---|
| 422 | `target_lang` missing or not a supported code |

---

## 5. Posts, comments and news

### `POST /translate/content`

Translate the items the user tapped **Translate** on. Send everything that should flip together in **one** request, for example a post and its visible comments.

**Request**

```ts
{
  items: Array<{
    type: "post" | "comment" | "news"
    id: string                  // post id / comment id as a string, news article_id (UUID)
    fields?: string[]           // optional: only these fields (see table). Omit for all.
  }>                            // 1 to 20 items
  target_lang?: string          // optional explicit override (§3)
}
```

**Translatable fields**

| `type` | Fields | Notes |
|---|---|---|
| `post` | `title`, `caption` | |
| `comment` | `content` | |
| `news` | `title`, `description`, `summary_bullets`, `impact_factor`, `impact_explanation` | **News card:** send `fields: ["title", "summary_bullets"]`. **Detail screen:** omit `fields`. The detail call then only pays for the extra fields. |

Unknown field names are ignored. An empty field on the source (e.g. no `description`) is simply absent from the result.

**Example**

```json
POST /translate/content
X-App-Language: hi

{
  "items": [
    { "type": "post", "id": "812" },
    { "type": "comment", "id": "4410" },
    { "type": "news", "id": "5b0c…e21", "fields": ["title", "summary_bullets"] }
  ]
}
```

**200**

```json
{
  "lang": "hi",
  "items": [
    {
      "type": "post", "id": "812", "status": "ready", "cached": true,
      "fields": {
        "title": "अंकुल ट्रेडर्स - शरबती गेहूं उपलब्ध",
        "caption": "इंदौर मंडी से 50 MT शरबती गेहूं रेडी है, रेट 2850 रु/क्विंटल, नेगोशिएबल।"
      }
    },
    {
      "type": "comment", "id": "4410", "status": "ready", "cached": false,
      "fields": { "content": "भाई 40 MT चाहिए, फाइनल रेट क्या लगेगा?" }
    },
    {
      "type": "news", "id": "5b0c…e21", "status": "in_progress", "cached": false, "fields": null
    }
  ]
}
```

**Response types**

```ts
{
  lang: string                       // the language actually used
  items: Array<{
    type: "post" | "comment" | "news"
    id: string                       // canonical form: "007" comes back as "7"
    status: "ready" | "in_progress" | "failed" | "not_found"
    fields: Record<string, string | string[]> | null
    cached: boolean                  // true = served from storage, no engine call
  }>
}
```

- `items` come back **in request order**, one per distinct item. Duplicates are merged.
- `summary_bullets` comes back as an array of the **same length and order** as the original.

**Item `status`**

| `status` | Meaning | `fields` | What the UI does |
|---|---|---|---|
| `ready` | Translated | every requested field | Show the translation |
| `in_progress` | Another user is translating this exact item right now | `null` | Retry after ~2 s (§7.3) |
| `failed` | The engine failed, timed out, or its output was rejected by a quality check | fields that did succeed, or `null` | Show the original + "Couldn't translate. Tap to retry" |
| `not_found` | No such item, deleted, or not visible to this user | `null` | Show the original; don't retry |

**Errors**

| Code | When | Body |
|---|---|---|
| 409 | No language to translate into (§3) | `{"detail": "Choose a language to translate into.", "code": "language_required", "supported": { "en": "English", ... }}` |
| 422 | 0 or more than 20 items, unknown `type`, unsupported `target_lang` | FastAPI validation body |
| 429 | Rate limit: 60 per user per hour, see below | `{"detail": "Too many requests. Retry after 3600 seconds."}` + `Retry-After` header |
| 503 | Translation engine not configured on the server | `{"detail": "Translation engine is not configured"}` |
| 401 | Token missing / expired | see §2 |

**How the backend handles it** (useful when reasoning about behaviour):
- **Stored first.** A translation is made once per item per language and stored. Every later request for it, from any user, returns `cached: true` in milliseconds and costs nothing.
- **Rate limit counts only requests that need the engine.** Re-opening translated items never uses up the limit.
- **Edited post →** the edited fields are translated again on the next tap. Old text is never shown against new content.
- **Quality checks.** A translation is rejected (never stored, reported `failed`) if it:
  - is not in the target script (e.g. left in English, or mixed with another alphabet), or
  - changed any number: prices, quantities, dates. Numbers always come back as `0-9` digits.
- **Timing.** A request that needs the engine takes about **2–3 s** typically. Up to 15 s per engine call before it gives up with `failed`. Show a loading state on the Translate control.

---

## 6. Chat

### 6.1 `POST /chat/messages/{message_id}/translate` — translate one message

For messages **the user received**, in DMs **and** groups. Never call it for the user's own messages.

```json
{ "target_lang": "hi" }
```

`target_lang` is optional (§3, chat rules). **Send only codes from §3.** This endpoint does not validate the code.

**200**

```ts
{ translated_text: string, target_lang: string, used_cache: boolean }
```

| Code | When | Body |
|---|---|---|
| 403 | User is not in that DM / group | `{"detail": "You do not have access to this message."}` |
| 404 | No such message, deleted, or no text | `{"detail": "Message not found or has no text body."}` |
| 429 | **60 per user per hour** (separate from the content limit). Only translations that reach the engine count; a 403, a 404 or a repeat served from cache never does | `{"detail": "Too many requests. Retry after 3600 seconds."}` |
| 502 | The translation failed the quality checks twice (wrong script, a number changed). Nothing was stored | `{"detail": "Couldn't translate this message reliably. Try again."}` |
| 503 | Engine not configured or unreachable | `{"detail": ...}` |

The translation is stored. In a DM with continuous mode on it also comes back on `GET .../messages` (§6.3). **In groups, keep the result client-side**, since group message lists never carry translations.

### 6.2 Continuous translation (DMs only)

Every incoming message in one DM is translated for this user automatically.

**`GET /chat/conversations/{conv_id}/continuous-translation`** → **200**

```ts
{ conversation_id: string, target_lang: string | null, continuous_enabled: boolean }
```

`continuous_enabled: false`, `target_lang: null` when never set. **Call it when opening a DM.** The setting lives on the server and survives reinstalls. Don't trust a cached toggle.

**`POST /chat/conversations/{conv_id}/continuous-translation`**

```json
{ "enabled": true, "target_lang": "hi" }
```

**200**: same shape as the GET. `target_lang` is optional; it is resolved once at opt-in and kept. `400 {"detail": "Continuous translation is only available for direct messages."}` for a group.

### 6.3 Reading chat translations back

`GET /chat/conversations/{conv_id}/messages` carries two extra fields on each message:

```ts
{
  id: string
  body: string | null
  translated_text: string | null   // null unless continuous is on AND a stored translation exists
  target_lang: string | null
  sent_at: string
  // ...other message fields unchanged
}
```

Show `translated_text` when present, else `body`. This covers scroll-back, reopening a thread, reconnecting after a dropped socket, and messages that arrived while offline. `GET /chat/groups/{group_id}/messages` always has these as `null`.

A message whose translation fails the quality checks stays untranslated: `translated_text` is `null` and no socket event is sent. It is not retried for 2 hours.

### 6.4 Socket event `message_translated`

Sent to the reader when a continuous-mode translation finishes:

```json
{ "message_id": "…", "translated_text": "hello", "target_lang": "en" }
```

A speed-up only: the same data is on the next `GET .../messages`. Replace the bubble's text if the message is on screen. Never depend on having received it.

---

## 7. Frontend integration

### 7.1 App start and settings
1. Send `X-App-Language: <ui language>` on every request (HTTP client interceptor).
2. On the settings screen, `GET /translate/preference`. Show a "Translate content into" picker built from `supported`, with `target_lang` selected (or nothing, if null).
3. On change, `PUT /translate/preference`.

### 7.2 Translate button on a post, comment or news item
```
tap "Translate"
  └─ POST /translate/content  { items: [the post + its visible comments] }
       ├─ 200 → per item:
       │     ready       → show translation under/over the original, button → "Show original"
       │     in_progress → keep loading; retry (7.3)
       │     failed      → show original + "Couldn't translate. Tap to retry"
       │     not_found   → show original, hide the button
       ├─ 409 language_required → open the language picker (use `supported` from the body)
       │                           → PUT /translate/preference → repeat the request
       ├─ 429 → toast "Translation limit reached, try again later"
       └─ 503 / network error → show original + "Translation unavailable"
```
- **News card:** `fields: ["title", "summary_bullets"]`. **News detail:** no `fields`.
- **"Show original" / "Translate" is a local toggle.** Keep the translation in memory keyed by `type:id:lang`, so toggling needs no request.
- Comments loaded later (pagination) while the post is in translated mode: send them in one `POST /translate/content` for the new page.
- Post author viewing their own post: don't show the button.
- When the app language changes, drop cached translations for the old language.

### 7.3 Retry policy
| Case | Retry |
|---|---|
| `in_progress` | Re-send only those items after 2 s, at most 3 times. Then treat as `failed`. |
| `failed` | Only when the user taps retry. |
| 429 | After `Retry-After` seconds. Don't auto-retry. |
| 5xx / network | Once when the user taps retry. |

Re-sending items that are already `ready` is harmless (they come back `cached: true` and don't count against the limit), but there's no need to.

### 7.4 Chat
1. Opening a DM: `GET .../continuous-translation` and set the toggle from it.
2. Toggle on: `POST .../continuous-translation {enabled: true, target_lang: <reading language>}`. Toggle off: `{enabled: false}`.
3. Render each message with `translated_text ?? body`.
4. On `message_translated`, update that bubble if it's on screen.
5. Long-press → Translate on a received message (DM or group): `POST /chat/messages/{id}/translate {target_lang: <reading language>}`. In groups, keep the result in memory. On `502`, show the original + "Couldn't translate. Tap to retry".

---

## 8. Limits

| | Limit |
|---|---|
| Items per `POST /translate/content` | 20 |
| Content translations needing the engine | 60 requests / user / hour (stored ones don't count) |
| Chat single-tap translations | 60 / user / hour, engine calls only (separate counter) |
| Continuous chat translation | DMs only, no per-message limit |
| Engine wait per call | 15 s, then `failed` |
| Wait on another user's in-flight translation | ~8 s, then `in_progress` |

---

## 9. Known limitations

- **Gujarati:** on the current engine (Gemini flash-lite), Hinglish posts translated into Gujarati often fail the script check. They come back `failed` instead of being shown half-translated. A model comparison is pending.
- **Names in feeds are not transliterated.** Author, business and group names stay as written. That is a separate, later feature. Names *inside* post text are transliterated (e.g. "Ankul Traders" → "अंकुल ट्रेडर्स").
- Group deals and personal deals are not translatable yet.
- Continuous translation does not exist for groups.
- Translations are machine-generated. Always keep "Show original" one tap away.

---

## 10. Status

| Part | State |
|---|---|
| Chat single tap, continuous, readback, socket | Live |
| Preference + content endpoints | Merged to `main` (`79e1bdd`), unit-tested. Deployed if the Actions run for that commit passed |
| Live engine quality | Probed on sample content: Hindi and Marathi good, Gujarati weak (see §9) |
| DB migration `c7d2e9f4a1b3` (adds `translations` to posts, comments, news) | Runs in the deploy workflow for that commit |
