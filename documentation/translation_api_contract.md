# Localisation — Frontend Contract

Everything the app needs to run in the user's language: choosing the app language, people's names in every language, translating posts / comments / news, and translating chat. Exact request and response shapes, error codes, limits, and the UI flows to build.

> **Status:** merged to `main` locally, **not yet deployed**. Two database migrations ship with it (`users.app_language`, `profile.name_i18n`). Shapes below are final unless this document changes.

---

## 1. At a glance

| Need | Endpoint / mechanism | § |
|---|---|---|
| Tell the backend the app's UI language | Header `X-App-Language` on **every** request | 2 |
| Save the app language (onboarding, settings) | `GET` / `PUT /auth/app-language` | 3 |
| Show people's names in the user's language | Automatic, from `X-App-Language` — no app change | 4.1 |
| Let a user give their name in another script | `name_i18n` on `POST /profile/` and `PATCH /profile/` | 4.2 |
| Suggest the spelling while the user types their name | `POST /translate/name-suggestions` | 4.3 |
| Find people by any spelling of their name | Automatic in `GET /connections/search` and `/search/suggestions` | 4.5 |
| Language to translate content into (when the app is in English) | `GET` / `PUT /translate/preference` | 5 |
| Translate posts, comments, news (on tap) | `POST /translate/content` | 6 |
| Translate chat messages | `POST /chat/messages/{id}/translate` and continuous mode | 7 |

**Nothing is translated unless the user asks**, with two exceptions that need no action from the app: **people's names** (shown in the viewer's language automatically) and **continuous chat translation** (when the user switches it on).

---

## 2. Conventions

### `X-App-Language` — send on every request

```
X-App-Language: hi
```

The language the app UI is in right now (`en` or `hi`). Set it once in the HTTP client so every request carries it, from the very first screen. It decides:

* which language **people's names** come back in (§4.1);
* the default target for **content translation** when the app is not in English (§5).

`hi-IN`, `HI`, `hi_IN` are accepted. A missing or unknown value is never an error — names then come back as their owners typed them.

### Authentication

```
Authorization: Bearer <access_token>
```

`/auth/app-language` and `/translate/name-suggestions` also accept the **onboarding token** (§3, §4.3), because they are used before the profile exists.

### Response envelopes — two styles

| Endpoints | Shape |
|---|---|
| `/auth/*`, `/profile/*`, `/connections/*` | Wrapped: `{"success": true, "message": "...", "data": {...}}` |
| `/translate/*`, `/chat/*` | **Bare** payload: `{"lang": "hi", ...}` |

Errors are FastAPI's: `{"detail": "..."}`; `422` carries a list in `detail`.

---

## 3. App language

The language the user runs the app in. Chosen during onboarding, changeable in settings. **Only `en` and `hi` today**; the list comes from the API (`supported`), so build the picker from it.

### `GET /auth/app-language`

**Auth:** onboarding token (after `POST /profile/user`) **or** access token.

**200**
```json
{
  "success": true,
  "message": "App language fetched",
  "data": { "app_language": "en", "supported": { "en": "English", "hi": "Hindi (Devanagari script)" } }
}
```

### `PUT /auth/app-language`

```json
{ "app_language": "hi" }
```

**200** — same shape as GET, with the saved value.

| Code | When |
|---|---|
| 404 | Called before the user row exists — call `POST /profile/user` first |
| 422 | Not one of `supported` |
| 401 | Token missing / expired |

**Why save it if the header already says it?** The server uses the saved value when there is no request from that user — e.g. the incoming-call screen is built in the **callee's** saved language (§4.4). Keep the two in sync: whenever the user changes the UI language, update the header **and** call `PUT`.

### Onboarding order

```
POST /auth/firebase-verify          -> onboarding token
POST /profile/user                  -> user row created
PUT  /auth/app-language  {hi}       -> language saved     (onboarding token)
POST /translate/name-suggestions    -> while typing the name (§4.3)
POST /profile/                      -> profile created, real tokens issued
```

The app may also show the language screen first and keep the choice locally until `POST /profile/user` has run; just send `X-App-Language` from the start.

---

## 4. People's names

A person's name is stored **exactly as they typed it** (`name`), plus the same name in other languages (`name_i18n`):

```json
"name": "तथागत",
"name_i18n": { "hi": "तथागत", "en": "Tathagata" }
```

* The typed name is stored under the language of its **script** (Devanagari → `hi`, English letters → `en`, Gujarati → `gu` …), whatever the app language.
* Spellings the person gave themselves are theirs and are never changed by the system.
* Missing languages are filled in automatically in the background, only when the system is confident (§4.6). Those are listed under `"auto"`:
  ```json
  { "en": "Akshay", "hi": "अक्षय", "auto": ["hi"] }
  ```
* `"failed"` may also appear (a language the system could not do confidently). Ignore both `"auto"` and `"failed"` for display.

### 4.1 Names in responses — automatic

**Every response that shows another person's name gives it in the viewer's `X-App-Language`** where we have it, and as typed otherwise. The field names do not change — the app only has to send the header.

| User typed | Viewer's app in English sees | Viewer's app in Hindi sees |
|---|---|---|
| `Akshay` | Akshay | अक्षय (once generated) |
| `तथागत` (gave "Tathagata") | Tathagata | तथागत |
| `Rama` (ambiguous — not generated) | Rama | Rama |

Covered: post feeds (`author_name`), comments (`commenter_name`), chat (sender, reply previews, shared-post author, conversation and group-chat lists, share sheet), connections lists and search, group members, another person's profile, share links, blocked users, call history.

**Not localised, by design:**

* **Your own profile** (`GET /profile/me`, `POST /profile/`, `PATCH /profile/`) returns `name` as typed plus the full `name_i18n` — the edit screen shows what the person entered.
* **A chat message arriving live on the socket** carries names as typed (it is built once, during the sender's request). Reopening or scrolling the conversation returns them in the viewer's language. Message **text** translation stays on-demand (§7).

### 4.2 Saving a name — profile create / edit

`POST /profile/` and `PATCH /profile/` accept an optional `name_i18n` with the person's **own** spellings in other languages:

```json
POST /profile/
{
  "name": "तथागत",
  "name_i18n": { "en": "Tathagata" },
  "role_id": 1,
  "commodities": [1],
  ...
}
```

* Keys: language codes from §5 (`en`, `hi`, `gu`, …). Values: 1–100 characters.
* You do not need to repeat `name` inside `name_i18n` — it is added under its own language automatically.
* **Changing `name`** discards the generated (`auto`) spellings — they were made from the old name — and they are regenerated. Spellings the person gave are kept unless they change them.

The profile response includes the stored dictionary:

```json
"data": { "profile": { "id": 812, "name": "तथागत", "name_i18n": { "hi": "तथागत", "en": "Tathagata" }, ... } }
```

| Code | When |
|---|---|
| 400 | `name_i18n` has an unknown language code, an empty value, or a value over 100 characters |

### 4.3 Name suggestions while typing

Offer the user the spelling of their name in the other language as they type it — e.g. a Hindi-app user types `तथागत`, the app offers `Tathagat` / `Tathagata`.

#### `POST /translate/name-suggestions`

**Auth:** onboarding token **or** access token.

```json
{ "text": "तथागत", "to": "en" }
```

**200**
```json
{ "source_lang": "hi", "to": "en", "suggestions": ["Tathagat", "Tathagata"] }
```

* `source_lang` — the language the typed text is in (from its script).
* `suggestions` — most common first, at most 4. **May be empty**; the user can always type their own.
* Every English ↔ Hindi suggestion is checked: a spelling that changes the name's sound — above all its ending (Akshay ↔ Akshaya) — is never offered. The only variant offered is a final "a" for a silent vowel (Tathagat / Tathagata), always after the closest spelling.
* Names typed in Gujarati, Punjabi, Bengali, Telugu, Kannada or Malayalam get their Hindi spelling exactly and instantly (`["गौरी"]` for `ગૌરી`).

| Code | When |
|---|---|
| 422 | `text` empty / over 100 characters / no letters; `to` not a supported code |
| 429 | 30 engine calls per user per 10 minutes (answers already seen are free) |
| 503 | Engine not configured |

#### When to call it — **once the user stops typing**

```
user types in the name field
  └─ wait until typing pauses (~500–700 ms), then:
       POST /translate/name-suggestions { text: <full name so far>, to: <other language> }
         └─ show suggestions as chips under a second field "Your name in English"
            ├─ prefill the field with suggestions[0]
            ├─ tap a chip -> fill the field
            └─ the user can always edit the field freely
on Save:
  POST /profile/ { name: <typed name>, name_i18n: { <other language>: <field value> } }
```

* Do **not** call on every keystroke. A new pause with the same text is free (cached).
* What the user picks or types is stored as their own spelling.
* For an English-app user, the same flow can offer the Hindi spelling (`to: "hi"`); it is optional — Hindi is generated for them automatically.

### 4.4 Incoming calls

The incoming-call screen (socket event `incoming_call`, and the push notification once notifications are enabled) shows the caller's name in **the callee's saved app language** (§3). Nothing to do in the app beyond keeping the saved language current.

### 4.5 Search

`GET /connections/search?q=...` and `GET /connections/search/suggestions?q=...` match `q` against the name as typed, **its other-language spellings**, and the business name. Searching `akshay` finds a person who typed `अक्षय` (once their English spelling exists), and the reverse. No app change.

### 4.6 How generated spellings are decided (for context)

* English → Hindi and Hindi → English: written by the AI engine, then **checked by fixed rules** that the spelling sounds the same — a changed ending is always rejected — and accepted only at ≥ 65% engine confidence. Names whose ending could be read two ways (Rama: रामा / राम) are not generated.
* Gujarati, Punjabi, Bengali, Telugu, Kannada, Malayalam → Hindi: exact letter-for-letter conversion, no AI.
* Tamil, Urdu → both: accepted only if the Hindi and English agree with each other.
* Anything not confident is left empty and the typed name is shown. Generation runs in the background right after sign-up / a name change and in a periodic backfill — a name may take a few minutes to appear in the other language.

---

## 5. Content translation language

### Languages

| Code | Language | | Code | Language |
|---|---|---|---|---|
| `en` | English | | `bn` | Bengali |
| `hi` | Hindi | | `ta` | Tamil |
| `mr` | Marathi | | `te` | Telugu |
| `gu` | Gujarati | | `kn` | Kannada |
| `pa` | Punjabi | | `ml` | Malayalam |
| `ur` | Urdu | | | |

### Which language content is translated into

**Posts, comments, news** (`POST /translate/content`) — first match wins:

1. `target_lang` in the request body
2. `X-App-Language`, if it is not English
3. the user's saved translation preference (below)
4. none → **`409 language_required`**: show the language picker

**Chat** (§7) resolves differently: body `target_lang` → this conversation's continuous setting → saved preference → automatic (English → Hindi, else → English). **Recommendation:** compute one *reading language* in the app with the rule for posts and pass it explicitly as `target_lang` to chat too.

### `GET /translate/preference`

```ts
{ target_lang: string | null, supported: Record<string, string> }
```

### `PUT /translate/preference`

```json
{ "target_lang": "mr" }
```

**200** same shape as GET. **422** unsupported code.

This is the language to translate content into **when the app itself is in English**. It is separate from the app language (§3).

---

## 6. Posts, comments and news

### `POST /translate/content`

Translate what the user tapped **Translate** on. Send everything that should flip together in **one** request (a post and its visible comments).

```ts
{
  items: Array<{
    type: "post" | "comment" | "news"
    id: string                  // post id / comment id as a string, news article_id (UUID)
    fields?: string[]           // optional — only these fields; omit for all
  }>                            // 1–20 items
  target_lang?: string
}
```

| `type` | Fields |
|---|---|
| `post` | `title`, `caption` |
| `comment` | `content` |
| `news` | `title`, `description`, `summary_bullets`, `impact_factor`, `impact_explanation` — **card:** `fields: ["title", "summary_bullets"]`; **detail:** omit `fields` |

**200**
```json
{
  "lang": "hi",
  "items": [
    { "type": "post", "id": "812", "status": "ready", "cached": true,
      "fields": { "title": "अंकुल ट्रेडर्स - शरबती गेहूं उपलब्ध", "caption": "इंदौर मंडी से 50 MT ..." } },
    { "type": "news", "id": "5b0c…e21", "status": "in_progress", "cached": false, "fields": null }
  ]
}
```

| `status` | Meaning | UI |
|---|---|---|
| `ready` | Translated; `fields` has every requested field | Show the translation, button → "Show original" |
| `in_progress` | Another user is translating this exact item right now | Retry after ~2 s (§8) |
| `failed` | Engine failed, timed out, or the output failed a quality check | Original + "Couldn't translate. Tap to retry" |
| `not_found` | No such item, or not visible | Original; no retry |

* `items` come back in request order; duplicates merged; `id` in canonical form (`"007"` → `"7"`).
* `summary_bullets` keeps the same number and order of bullets.
* Numbers always come back as `0-9` digits, and every price, quantity and date is guaranteed unchanged — a translation that changes one is never returned.

| Code | When | Body |
|---|---|---|
| 409 | No language to translate into | `{"detail": "...", "code": "language_required", "supported": {...}}` |
| 422 | 0 or > 20 items, unknown `type`, unsupported `target_lang` | validation body |
| 429 | 60 engine calls / user / hour (stored translations do not count) | `{"detail": "Too many requests. Retry after 3600 seconds."}` + `Retry-After` |
| 503 | Engine not configured | `{"detail": "Translation engine is not configured"}` |

A request that needs the engine typically takes **2–3 s** (up to 15 s per engine call). Show a loading state on the Translate control.

---

## 7. Chat

### 7.1 `POST /chat/messages/{message_id}/translate` — one message

For messages the user **received**, in DMs and groups.

```json
{ "target_lang": "hi" }
```

**200**
```ts
{ translated_text: string, target_lang: string, used_cache: boolean }
```

| Code | When |
|---|---|
| 403 | Not in that DM / group |
| 404 | No such message, deleted, or no text |
| 429 | 60 per user per hour — only translations that reach the engine count |
| 502 | The translation failed the quality checks twice; nothing stored — `"Couldn't translate this message reliably. Try again."` |
| 503 | Engine not configured or unreachable |

In groups keep the result in memory — group message lists never carry translations.

### 7.2 Continuous translation (DMs only)

`GET /chat/conversations/{conv_id}/continuous-translation` → `{ conversation_id, target_lang, continuous_enabled }`. Call it when opening a DM.

`POST /chat/conversations/{conv_id}/continuous-translation` with `{ "enabled": true, "target_lang": "hi" }` → same shape. `400` for a group.

### 7.3 Reading translations back

`GET /chat/conversations/{conv_id}/messages` carries `translated_text` and `target_lang` on each message (null unless continuous is on and a translation is stored). Show `translated_text ?? body`. A message whose translation fails the checks stays untranslated (`null`) and is not retried for 2 hours.

### 7.4 Socket `message_translated`

`{ "message_id": "…", "translated_text": "hello", "target_lang": "en" }` — sent when a continuous translation finishes. Replace the bubble text if on screen; never depend on receiving it.

---

## 8. Integration checklist

**Everywhere**
1. HTTP client interceptor: `X-App-Language: <ui language>` on every request.
2. When the UI language changes: update the header, call `PUT /auth/app-language`, and drop any cached content translations.

**Onboarding**
3. Language screen → after `POST /profile/user`, `PUT /auth/app-language`.
4. Name screen → name field + "Your name in English/Hindi" field, filled from `POST /translate/name-suggestions` once typing pauses (§4.3).
5. `POST /profile/` with `name` and `name_i18n`.

**Profile edit**
6. Show `name` and `name_i18n` from `GET /profile/me`; same suggestion flow; `PATCH /profile/` with what changed.

**Settings**
7. App language picker (`GET`/`PUT /auth/app-language`).
8. "Translate content into" picker for English-app users (`GET`/`PUT /translate/preference`).

**Posts, comments, news**
9. Translate button → `POST /translate/content` (post + visible comments in one call; news card vs detail `fields`); "Show original" is a local toggle.
10. Handle `409 language_required` by opening the picker, then retrying.

**Chat**
11. Opening a DM: `GET .../continuous-translation`; toggle with `POST`.
12. Render `translated_text ?? body`; update on `message_translated`.
13. Long-press → Translate: `POST /chat/messages/{id}/translate`; on `502` show "Couldn't translate. Tap to retry".

### Retry policy

| Case | Retry |
|---|---|
| `in_progress` | Only those items, after 2 s, at most 3 times; then treat as `failed` |
| `failed` / `502` | Only when the user taps retry |
| `429` | After `Retry-After`; no auto-retry |
| 5xx / network | Once, on user tap |

---

## 9. Limits

| | Limit |
|---|---|
| Items per `POST /translate/content` | 20 |
| Content translation engine calls | 60 / user / hour (stored ones free) |
| Chat single-tap engine calls | 60 / user / hour (separate counter) |
| Name suggestion engine calls | 30 / user / 10 min (cached answers free) |
| Name length (`name`, `name_i18n` values, suggestion `text`) | 100 characters |
| Engine wait per call | 15 s |

---

## 10. Known limitations

* **App languages:** only English and Hindi today. Names are stored for any of the 11 languages; adding an app language needs no API change.
* **Generated name spellings** are correct in sound but may not be the person's own spelling (`সৌরভ` → "Saurabh", where the person may write "Sourav"). This is why the onboarding name screen asks for their own spelling. Owner confirmation of generated spellings is planned for a later stage.
* **Live chat messages** carry names as typed until the conversation is reopened (§4.1).
* **Push notifications** are not enabled yet; when they are, the incoming-call notification already uses the callee's language.
* **Gujarati content translation** is weaker than Hindi/Marathi/Bengali/Tamil on the current model; more output fails the quality checks and comes back `failed`.
* Business names and group names are not transliterated yet; group deals and personal deals are not translatable yet.
