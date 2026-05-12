# Profile Module — Developer Guide & Test Reference

A complete reference for the onboarding flow, profile creation, and profile management APIs.

Base URL (production): `https://vanijyaa-backend.onrender.com`

---

## Table of Contents

1. [Local Setup](#1-local-setup)
2. [How Auth Works](#2-how-auth-works)
3. [Seed the Database](#3-seed-the-database)
4. [Get an Onboarding Token](#4-get-an-onboarding-token)
5. [API Quick Reference](#5-api-quick-reference)
6. [Onboarding Flow](#6-onboarding-flow)
7. [Profile APIs](#7-profile-apis)
8. [Database Schema](#8-database-schema)
9. [Error Reference](#9-error-reference)

---

## 1. Local Setup

**Start the server:**
```bash
uvicorn main:app --reload
```

Server runs at `http://localhost:8000`.
Swagger UI at `http://localhost:8000/docs` — use this to test all endpoints interactively.

**Required env vars (add to `.env` and Render):**
```
DATABASE_URL=postgresql+asyncpg://...
SYNC_DATABASE_URL=postgresql+psycopg2://...
DATABASE_SERVICE_KEY=<supabase service role key>
DATABASE_STORAGE_URL=https://<project-ref>.supabase.co   ← required for avatar uploads
DATABASE_STORAGE_BUCKET=avatars
```

---

## 2. How Auth Works

The profile module uses **two different token types** depending on the stage:

| Stage | Endpoints | Auth mechanism |
|---|---|---|
| **Onboarding (new users)** | `POST /profile/user` and `POST /profile/` | `Authorization: Bearer <onboarding_token>` |
| **Post-registration** | All other endpoints | `Authorization: Bearer <access_token>` |

### Onboarding token
- Issued by `POST /auth/firebase-verify` for new users
- JWT signed with HS256, expires in 15 minutes
- Contains: `user_id`, `phone_number`, `country_code`, `token_type: "onboarding"`

### Access token
- Issued by `POST /profile/` (onboarding Step 2) inside the response body
- Contains: `user_id` (`sub`), `profile_id` (`pid`), `session_id` (`jti`), `type: "access"`
- The acting user's identity is derived exclusively from this token — **never** from a query or path parameter
- Example: `GET /profile/me` with `Authorization: Bearer <access_token>`

---

## 3. Seed the Database

Profiles require valid `role_id`, `commodity` IDs, and `interest` IDs. These must exist in the lookup tables first.

**Run once:**
```bash
python scripts/seed.py
```

**Current seed data:**

### Roles
| Name | ID |
|---|---|
| `trader` | `1` |
| `broker` | `2` |
| `exporter` | `3` |

### Commodities
| Name | ID |
|---|---|
| `rice` | `1` |
| `cotton` | `2` |
| `sugar` | `3` |

### Interests
| Name | ID |
|---|---|
| `connections` | `1` |
| `leads` | `2` |
| `news` | `3` |

---

## 4. Get an Onboarding Token

Auth uses **Firebase Phone OTP**. The client obtains a Firebase ID token after verifying the OTP, then sends it to the backend.

### Step 1 — Verify Firebase token (get onboarding token)

```bash
curl -X POST http://localhost:8000/auth/firebase-verify \
  -H "Content-Type: application/json" \
  -d '{ "firebase_id_token": "<FIREBASE_ID_TOKEN>" }'
```

**Response — new user:**
```json
{
    "success": true,
    "data": {
        "onboarding_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        "token_type": "bearer",
        "expires_in": 900
    }
}
```

**Response — returning user (profile already exists):**
```json
{
    "success": true,
    "data": {
        "user_id": "c37a3257-dc3f-43be-9fb0-33cf918b11ff"
    }
}
```

Copy the `onboarding_token` — use it for `POST /profile/user` and `POST /profile/`.  
Returning users get `user_id` directly and skip the onboarding steps.

---

**To use in Swagger UI (`/docs`):**
1. Open `http://localhost:8000/docs`
2. Click **Authorize** (top right, lock icon)
3. Paste the onboarding token in the `Value` field — click **Authorize**
4. All requests now send `Authorization: Bearer <token>` automatically

**To use in Postman / curl:**
```
Authorization: Bearer <onboarding_token>
```

---

## 5. API Quick Reference

| Method | Endpoint | Auth | What it does |
|---|---|---|---|
| `POST` | `/profile/user` | Bearer onboarding token | Create user row |
| `POST` | `/profile/` | Bearer onboarding token | Create profile → returns access + refresh tokens |
| `GET` | `/profile/me` | Bearer access token | Fetch your own full profile |
| `PATCH` | `/profile/` | Bearer access token | Update your profile |
| `GET` | `/profile/avatar-upload-url` | Bearer access token | Get signed URL to upload avatar to Supabase |
| `PATCH` | `/profile/avatar` | Bearer access token | Persist avatar URL after Supabase upload |
| `PATCH` | `/profile/user/fcm-token` | Bearer access token | Register / update FCM push token |
| `POST` | `/profile/verify` | Bearer access token | Submit verification documents |
| `DELETE` | `/profile/` | Bearer access token | Hard delete profile row only |
| `DELETE` | `/profile/user` | Bearer access token | Permanently delete user and all associated data |
| `GET` | `/profile/{profile_id}` | None (public) | Public view of any profile |

---

## 6. Onboarding Flow

Profile creation is a **two-step process** — both steps use the **onboarding token**.

```
Step 1: POST /profile/user    ← creates the User row (phone, country_code)
Step 2: POST /profile/        ← creates Profile + commodities + interests
```

Both steps must use the **same onboarding token** issued in Section 4.

> If a user's phone number already has a user row but no profile yet (incomplete onboarding), Step 1 reuses the existing UUID so there is no phone conflict.

---

### Step 1 — `POST /profile/user`

Creates the `users` row. Must be called before creating a profile.

**Auth:** `Authorization: Bearer <ONBOARDING_TOKEN>`  
**Body:** None — phone number and country code are read from the token.

**Example (curl):**
```bash
curl -X POST http://localhost:8000/profile/user \
  -H "Authorization: Bearer <ONBOARDING_TOKEN>"
```

**Success `201`:**
```json
{
    "success": true,
    "message": "User created successfully",
    "data": {
        "id": "c37a3257-dc3f-43be-9fb0-33cf918b11ff",
        "phone_number": "9876543210",
        "country_code": "+91",
        "created_at": "2026-04-16T10:00:00.000000"
    }
}
```

**Error `409`** — active account already exists:
```json
{ "detail": "Phone number already registered" }
```

---

### Step 2 — `POST /profile/`

Creates the profile. Call immediately after Step 1 with the same token.

**Auth:** `Authorization: Bearer <ONBOARDING_TOKEN>`  
**Content-Type:** `application/json`

**Request body:**
```json
{
    "name": "Ravi Traders",
    "role_id": 1,
    "commodities": [1, 2],
    "interests": [1, 2],
    "quantity_min": 100,
    "quantity_max": 500,
    "business_name": "Ravi Agro Pvt Ltd",
    "city": "Mumbai",
    "state": "Maharashtra",
    "latitude": 19.076,
    "longitude": 72.877
}
```

**Field reference:**

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | Yes | Display name |
| `role_id` | int | Yes | `1`=trader, `2`=broker, `3`=exporter |
| `commodities` | int[] | Yes | At least one — `1`=rice, `2`=cotton, `3`=sugar |
| `interests` | int[] | Yes | At least one — `1`=connections, `2`=leads, `3`=news |
| `quantity_min` | float | Yes | Minimum trade quantity in MT |
| `quantity_max` | float | Yes | Must be ≥ `quantity_min` |
| `business_name` | string | No | Optional business name |
| `city` | string | No | City name e.g. `"Mumbai"` |
| `state` | string | No | State name e.g. `"Maharashtra"` |
| `latitude` | float | Yes | Business location latitude |
| `longitude` | float | Yes | Business location longitude |

**Success `201`:**
```json
{
    "success": true,
    "message": "Profile created successfully.",
    "data": {
        "profile": {
            "id": 1,
            "name": "Ravi Traders",
            "role_id": 1,
            "commodities": [
                { "id": 1, "name": "rice" },
                { "id": 2, "name": "cotton" }
            ],
            "interests": [
                { "id": 1, "name": "connections" },
                { "id": 2, "name": "leads" }
            ],
            "is_verified": false,
            "is_user_verified": false,
            "is_business_verified": false,
            "followers_count": 0,
            "business_name": "Ravi Agro Pvt Ltd",
            "city": "Mumbai",
            "state": "Maharashtra",
            "latitude": 19.076,
            "longitude": 72.877,
            "avatar_url": null
        },
        "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        "token_type": "bearer",
        "expires_in": 1800
    }
}
```

> **Save the `access_token`** — use it as `Authorization: Bearer <access_token>` for all subsequent profile, post, feed, news, groups, and connections calls.

**Error `409`** — profile already exists:
```json
{ "detail": "Profile already exists for this user" }
```

**Error `400`** — invalid IDs or quantity mismatch:
```json
{ "detail": "Invalid commodity_ids: 99" }
```

---

## 7. Profile APIs

All endpoints in this section require `Authorization: Bearer <access_token>`. The acting user's identity is read from the token — no `user_id` query parameter needed or accepted.

---

### `GET /profile/me`

Fetch your own full profile.

**Example:**
```bash
curl "http://localhost:8000/profile/me" \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

**Success `200`:**
```json
{
    "success": true,
    "message": "Profile fetched successfully",
    "data": {
        "id": 1,
        "name": "Ravi Traders",
        "role_id": 1,
        "commodities": [
            { "id": 1, "name": "rice" }
        ],
        "interests": [
            { "id": 1, "name": "connections" }
        ],
        "is_verified": false,
        "is_user_verified": false,
        "is_business_verified": false,
        "followers_count": 0,
        "business_name": "Ravi Agro Pvt Ltd",
        "city": "Mumbai",
        "state": "Maharashtra",
        "latitude": 19.076,
        "longitude": 72.877,
        "avatar_url": "https://<project>.supabase.co/storage/v1/object/public/avatars/<user_id>.jpg"
    }
}
```

---

### Avatar Upload — Two-Step Flow

Uploading an avatar is a two-step process: get a signed URL, upload the file directly to Supabase, then persist the URL.

#### Step 1 — `GET /profile/avatar-upload-url`

Get a short-lived signed upload URL from Supabase Storage.

**Query params:**

| Param | Type | Required | Values |
|---|---|---|---|
| `content_type` | string | Yes | `image/jpeg`, `image/png`, `image/webp` |

**Example:**
```bash
curl "http://localhost:8000/profile/avatar-upload-url?content_type=image/jpeg" \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

**Success `200`:**
```json
{
  "success": true,
  "message": "Upload URL generated",
  "data": {
    "upload_url": "https://<project>.supabase.co/storage/v1/object/sign/avatars/...",
    "public_url": "https://<project>.supabase.co/storage/v1/object/public/avatars/<uuid>.jpg"
  }
}
```

#### Step 2a — Upload file to Supabase

```bash
curl -X PUT "<upload_url>" \
  -H "Content-Type: image/jpeg" \
  --data-binary @/path/to/photo.jpg
```

#### Step 2b — `PATCH /profile/avatar`

Persist the public URL to the profile after upload.

**Request body:**
```json
{ "avatar_url": "<public_url from step 1>" }
```

**Example:**
```bash
curl -X PATCH "http://localhost:8000/profile/avatar" \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{ "avatar_url": "https://<project>.supabase.co/storage/v1/object/public/avatars/<uuid>.jpg" }'
```

**Success `200`:**
```json
{
    "success": true,
    "message": "Avatar updated successfully",
    "data": {
        "avatar_url": "https://<project>.supabase.co/storage/v1/object/public/avatars/<user_id>.jpg"
    }
}
```

**Error `400`** — unsupported file type:
```json
{ "detail": "Unsupported image type 'image/gif'. Allowed: jpeg, png, webp." }
```

---

### `PATCH /profile/`

Update your profile. All fields are optional — only send what you want to change.

**Auth:** `Authorization: Bearer <ACCESS_TOKEN>`

**Request body:**
```json
{
    "name": "Ravi Global Traders",
    "commodities": [3],
    "interests": [1, 3],
    "quantity_min": 200,
    "quantity_max": 1000,
    "business_name": "Ravi Agro International",
    "city": "Pune",
    "state": "Maharashtra",
    "latitude": 18.520,
    "longitude": 73.856
}
```

| Field | Type | Notes |
|---|---|---|
| `name` | string | Display name |
| `commodities` | int[] | Full replacement list |
| `interests` | int[] | Full replacement list |
| `quantity_min` | float | |
| `quantity_max` | float | Must be ≥ `quantity_min` |
| `business_name` | string | |
| `city` | string | |
| `state` | string | |
| `latitude` | float | |
| `longitude` | float | |

**Commodity / interest update behaviour:**  
Pass the complete new list. Items not in the list are removed. Items already present are kept. New items are added.

**Success `200`:**
```json
{
    "success": true,
    "message": "Profile updated successfully",
    "data": { "..." }
}
```

---

### `PATCH /profile/user/fcm-token`

Register or update the device FCM push token. Call this after login and whenever the token is refreshed by Firebase.

**Example:**
```bash
curl -X PATCH "http://localhost:8000/profile/user/fcm-token" \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{ "fcm_token": "<FIREBASE_FCM_TOKEN>" }'
```

**Request body:**

| Field | Type | Required | Notes |
|---|---|---|---|
| `fcm_token` | string | Yes | Firebase Cloud Messaging device token |

**Success `200`:**
```json
{
    "success": true,
    "message": "FCM token updated",
    "data": null
}
```

---

### `POST /profile/verify`

Submit identity or business verification documents for admin review.

**Content-Type:** `multipart/form-data`

**Example:**
```bash
curl -X POST "http://localhost:8000/profile/verify" \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -F "identity_proof=@/path/to/aadhaar.jpg" \
  -F "business_proof=@/path/to/gst_cert.pdf"
```

**Form fields:**

| Field | Type | Required | Notes |
|---|---|---|---|
| `identity_proof` | file | No | Government-issued ID scan (jpeg/png/pdf) |
| `business_proof` | file | No | GST certificate or business registration (jpeg/png/pdf) |

At least one document must be provided.

**Success `200`:**
```json
{
    "success": true,
    "message": "Verification documents submitted",
    "data": null
}
```

**Error `400`** — no files provided:
```json
{ "detail": "At least one document must be provided." }
```

---

### `DELETE /profile/user` — Permanently Delete Account

Hard deletes the user row from the database. All associated data is removed immediately via `ON DELETE CASCADE` — profile, embeddings, group memberships, news engagement, and cluster taste records are all gone. This is **not reversible**. If the same phone number registers again afterwards, it is treated as a completely new user.

```bash
curl -X DELETE "http://localhost:8000/profile/user" \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

**Success `200`:**
```json
{
    "success": true,
    "message": "User and all associated data deleted successfully",
    "data": null
}

---

### `DELETE /profile/` — Delete Profile Only

Hard deletes the profile row (commodities, interests, documents cascade). The `users` row remains intact.

```bash
curl -X DELETE "http://localhost:8000/profile/" \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

**Success `200`:**
```json
{
    "success": true,
    "message": "Profile deleted successfully",
    "data": null
}
```

---

### `GET /profile/{profile_id}` — Public View

View any user's public profile. **No auth required.**

| Param | Type | Description |
|---|---|---|
| `profile_id` | int | The profile's integer ID (from your `/me` response) |

**Example:**
```bash
curl http://localhost:8000/profile/1
```

**Success `200`:**
```json
{
    "success": true,
    "message": "Profile fetched successfully",
    "data": {
        "id": 1,
        "name": "Ravi Traders",
        "role_id": 1,
        "is_verified": false,
        "commodities": [
            { "id": 1, "name": "rice" }
        ],
        "business_name": "Ravi Agro Pvt Ltd",
        "city": "Mumbai",
        "state": "Maharashtra",
        "latitude": 19.076,
        "longitude": 72.877,
        "posts_count": 0,
        "avatar_url": null
    }
}
```

---

## 8. Database Schema

```
users                  — auth identity (phone, country_code, fcm_token, access_token, is_active)
roles                  — trader / broker / exporter
profile                — main profile (city, state, latitude, longitude, avatar_url, ...)
commodities            — rice / cotton / sugar / ...
profile_commodities    — profile ↔ commodity (many-to-many, CASCADE on profile delete)
interests              — connections / leads / news
profile_interests      — profile ↔ interest (many-to-many, CASCADE on profile delete)
profile_documents      — uploaded docs per profile (CASCADE on profile delete)
user_embeddings        — IS vector for matching (built on profile create/update)
```

**FK cascade chain on user delete (`DELETE /profile/user`):**
```
users → profile → profile_commodities
                → profile_interests
                → profile_documents
      → user_embeddings
      → news_engagement
      → user_cluster_taste
      → group_members
      → groups.created_by SET NULL
```

Run migrations:
```bash
alembic upgrade head
```

Check current migration state:
```bash
alembic current
```

---

## 9. Error Reference

| Status | When it happens |
|---|---|
| `400` | Invalid IDs (role/commodity/interest not in DB), `quantity_min > quantity_max`, unsupported avatar type |
| `401` | Missing, expired, or wrong token type (onboarding token required on step 1-2; access token required everywhere else) |
| `404` | User or profile not found |
| `409` | Active account already registered with this phone number, or profile already exists |
| `422` | Missing required field or wrong data type (FastAPI validation) |

All errors follow FastAPI's default shape:
```json
{
    "detail": "Human-readable description of what went wrong."
}
```

---

## Full Test Sequence (copy-paste order)

```bash
# 1. Start server
uvicorn main:app --reload

# 2. Seed lookup tables (run once)
python scripts/seed.py

# 3. Verify Firebase ID token — get onboarding_token from response
curl -X POST http://localhost:8000/auth/firebase-verify \
  -H "Content-Type: application/json" \
  -d '{ "firebase_id_token": "<FIREBASE_ID_TOKEN>" }'

# 4. Create user row (paste ONBOARDING_TOKEN from step 3)
curl -X POST http://localhost:8000/profile/user \
  -H "Authorization: Bearer <ONBOARDING_TOKEN>"

# 5. Create profile (same ONBOARDING_TOKEN from step 3)
#    → response contains access_token and refresh_token — save access_token for steps 6+
curl -X POST http://localhost:8000/profile/ \
  -H "Authorization: Bearer <ONBOARDING_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Ravi Traders",
    "role_id": 1,
    "commodities": [1, 2],
    "interests": [1, 2],
    "quantity_min": 100,
    "quantity_max": 500,
    "business_name": "Ravi Agro",
    "city": "Mumbai",
    "state": "Maharashtra",
    "latitude": 19.076,
    "longitude": 72.877
  }'

# 6. Fetch your profile (use ACCESS_TOKEN from step 5 response)
curl "http://localhost:8000/profile/me" \
  -H "Authorization: Bearer <ACCESS_TOKEN>"

# 7. Get a signed upload URL for avatar
curl "http://localhost:8000/profile/avatar-upload-url?content_type=image/jpeg" \
  -H "Authorization: Bearer <ACCESS_TOKEN>"

# 7b. Upload file directly to Supabase using the upload_url from step 7
curl -X PUT "<UPLOAD_URL>" \
  -H "Content-Type: image/jpeg" \
  --data-binary @/path/to/photo.jpg

# 7c. Persist the public_url from step 7 to the profile
curl -X PATCH "http://localhost:8000/profile/avatar" \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{ "avatar_url": "<PUBLIC_URL>" }'

# 8. Update name and city only
curl -X PATCH "http://localhost:8000/profile/" \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{ "name": "Ravi Global Traders", "city": "Pune" }'

# 9. Public profile view (replace PROFILE_ID with the int id from step 6 response)
curl http://localhost:8000/profile/<PROFILE_ID>

# 10. Permanently delete account (removes user row and all data via CASCADE)
curl -X DELETE "http://localhost:8000/profile/user" \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```
