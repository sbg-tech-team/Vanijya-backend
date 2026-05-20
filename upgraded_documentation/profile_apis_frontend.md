# Profile Module — Frontend API Documentation

> **Base URL:** `https://<your-server>/profile`  
> **Auth header:** `Authorization: Bearer <access_token>` (where required)  
> **All responses** are wrapped: `{ "status": "success", "message": "...", "data": { ... } }`

---

## Quick Reference

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/profile/user` | Onboarding token | Onboarding step 1 — create user row |
| POST | `/profile/` | Onboarding token | Onboarding step 2 — create profile + get tokens |
| GET | `/profile/me` | Access token | Get own full profile |
| PATCH | `/profile/` | Access token | Update profile fields |
| PATCH | `/profile/user/fcm-token` | Access token | Save FCM push token |
| GET | `/profile/avatar-upload-url` | Access token | Step 1 of avatar upload — get signed URL |
| PATCH | `/profile/avatar` | Access token | Step 2 of avatar upload — save URL to DB |
| DELETE | `/profile/` | Access token | Delete profile only |
| DELETE | `/profile/user` | Access token | Delete account + all data |
| GET | `/profile/{profile_id}` | None | Public profile view |

> **KYC / KYB verification** has its own module. See `verification_module.md`.

---

## Reference Data (Hardcoded Values)

These values are static — no API call needed. Hardcode them in the app.

### Roles
| id | name | Description |
|----|------|-------------|
| 1 | Trader | Buys and sells commodities directly |
| 2 | Broker | Facilitates deals between parties |
| 3 | Exporter | Exports commodities internationally |

### Commodities
| id | name |
|----|------|
| 1 | Rice |
| 2 | Cotton |
| 3 | Sugar |

### Interests
| id | name |
|----|------|
| 1 | Connections |
| 2 | Leads |
| 3 | News |

---

## Onboarding Step 1 — Create User Row

> Use after receiving `onboarding_token` from `POST /auth/firebase-verify`.  
> You do **not** send any body — user info (phone, country code) is read from the token itself.

```
POST /profile/user
Authorization: Bearer <onboarding_token>
```

**Request body:** none

**Response `data`:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "phone_number": "9876543210",
  "country_code": "+91",
  "created_at": "2025-10-01T10:00:00Z"
}
```

**Errors:**

| Status | Detail | When |
|--------|--------|------|
| 401 | Onboarding token has expired | Token older than 30 minutes |
| 401 | Invalid onboarding token | Bad or tampered token |
| 409 | Phone number already registered | Duplicate phone (rare edge case) |

---

## Onboarding Step 2 — Create Profile

> The **last onboarding step**. Returns real `access_token` + `refresh_token`.  
> From this point the user is fully logged in — store both tokens and navigate to the home screen.

```
POST /profile/
Authorization: Bearer <onboarding_token>
Content-Type: application/json
```

**Request body:**
```json
{
  "role_id": 1,
  "name": "Sanket Suryawanshi",
  "commodities": [1, 2],
  "interests": [1, 3],
  "quantity_min": 100.0,
  "quantity_max": 5000.0,
  "business_name": "Shri Balaji Global",
  "city": "Pune",
  "state": "Maharashtra",
  "latitude": 18.5204,
  "longitude": 73.8567
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `role_id` | int | Yes | 1 = Trader, 2 = Broker, 3 = Exporter |
| `name` | string | Yes | Full name |
| `commodities` | int[] | Yes | Array of commodity IDs (multi-select) |
| `interests` | int[] | Yes | Array of interest IDs (multi-select) |
| `quantity_min` | float | Yes | Minimum quantity the user deals in |
| `quantity_max` | float | Yes | Maximum quantity — must be ≥ `quantity_min` |
| `business_name` | string | No | Company / firm name |
| `city` | string | No | City text |
| `state` | string | No | State text |
| `latitude` | float | Yes | Decimal degrees — use device GPS or geocoding |
| `longitude` | float | Yes | Decimal degrees |

**Response `data`:**
```json
{
  "profile": {
    "id": 42,
    "name": "Sanket Suryawanshi",
    "role_id": 1,
    "phone_number": "9876543210",
    "country_code": "+91",
    "commodities": [
      { "id": 1, "name": "Rice" },
      { "id": 2, "name": "Cotton" }
    ],
    "interests": [
      { "id": 1, "name": "Connections" },
      { "id": 3, "name": "News" }
    ],
    "is_user_verified": false,
    "is_business_verified": false,
    "followers_count": 0,
    "following_count": 0,
    "posts_count": 0,
    "business_name": "Shri Balaji Global",
    "city": "Pune",
    "state": "Maharashtra",
    "latitude": 18.5204,
    "longitude": 73.8567,
    "avatar_url": null
  },
  "access_token": "<jwt>",
  "refresh_token": "<opaque-string>",
  "token_type": "bearer",
  "expires_in": 36000
}
```

**What to store after this call:**
- `access_token` — send in `Authorization: Bearer` header on every subsequent API call
- `refresh_token` — store securely (Keychain / EncryptedSharedPrefs); use to renew access tokens
- `data.profile.id` — this is the `profile_id`, needed when navigating to a public profile or uploading an avatar

**Errors:**

| Status | Detail | When |
|--------|--------|------|
| 400 | quantity_min cannot be greater than quantity_max | Validation failed |
| 400 | Invalid role_id | Not 1, 2, or 3 |
| 400 | Invalid commodity_ids / interest_ids | IDs not in DB |
| 404 | User not found — create user first via POST /profile/user | Step 1 was skipped |
| 409 | Profile already exists for this user | Profile creation called twice |

---

## Get My Profile

> Returns the authenticated user's own full profile including phone number and counts.

```
GET /profile/me
Authorization: Bearer <access_token>
```

**Request body:** none

**Response `data`:**
```json
{
  "id": 42,
  "name": "Sanket Suryawanshi",
  "role_id": 1,
  "phone_number": "9876543210",
  "country_code": "+91",
  "commodities": [
    { "id": 1, "name": "Rice" }
  ],
  "interests": [
    { "id": 1, "name": "Connections" }
  ],
  "is_user_verified": false,
  "is_business_verified": false,
  "followers_count": 47,
  "following_count": 23,
  "posts_count": 12,
  "business_name": "Shri Balaji Global",
  "city": "Pune",
  "state": "Maharashtra",
  "latitude": 18.5204,
  "longitude": 73.8567,
  "avatar_url": "https://your-supabase.supabase.co/storage/v1/object/public/avatars/42.jpg"
}
```

**Verification flags:**

| Field | Meaning | Set by |
|-------|---------|--------|
| `is_user_verified` | PAN or Aadhaar verified (KYC) | `POST /verification/kyc/pan` |
| `is_business_verified` | GST or IEC verified (KYB) | `POST /verification/kyb/gst` or `/kyb/iec` |

Both flags start as `false` and are set to `true` by the verification module upon successful document verification. See `verification_module.md` for the full verification flow.

**Errors:**

| Status | Detail | When |
|--------|--------|------|
| 401 | Access token has expired | Use `POST /auth/refresh` |
| 401 | Invalid access token | Token tampered / wrong env |
| 404 | Profile not found | User has no profile yet |

---

## Update Profile

> All fields are optional — send only what changed.  
> Role is **not** editable after creation.

```
PATCH /profile/
Authorization: Bearer <access_token>
Content-Type: application/json
```

**Request body (all fields optional):**
```json
{
  "name": "Sanket S.",
  "business_name": "Balaji Exports Pvt Ltd",
  "city": "Mumbai",
  "state": "Maharashtra",
  "latitude": 19.0760,
  "longitude": 72.8777,
  "commodities": [1, 3],
  "interests": [2],
  "quantity_min": 200.0,
  "quantity_max": 10000.0
}
```

> **Note on commodities/interests:** The array you send is the **complete new set**, not a diff.  
> If the user currently has [Rice, Cotton] and you send `[1, 3]`, the result is [Rice, Sugar].

**Response `data`:** same shape as `GET /profile/me` (full `ProfileResponse`)

**Errors:**

| Status | Detail | When |
|--------|--------|------|
| 400 | quantity_min cannot exceed quantity_max | Bad range |
| 404 | Profile not found | — |

---

## Update FCM Token

> Call this on every app launch (after login) and whenever Firebase gives you a new token via `onTokenRefresh`.

```
PATCH /profile/user/fcm-token
Authorization: Bearer <access_token>
Content-Type: application/json
```

**Request body:**
```json
{
  "fcm_token": "fOTJHvPa..."
}
```

**Response `data`:** `null` (message: "FCM token updated")

---

## Avatar Upload — Step 1: Get Signed URL

```
GET /profile/avatar-upload-url?content_type=image/jpeg
Authorization: Bearer <access_token>
```

**Query params:**

| Param | Required | Valid values |
|-------|----------|-------------|
| `content_type` | Yes | `image/jpeg`, `image/png`, `image/webp` |

**Response `data`:**
```json
{
  "signed_url": "https://your-supabase.supabase.co/storage/v1/object/sign/avatars/42.jpg?token=...",
  "avatar_url": "https://your-supabase.supabase.co/storage/v1/object/public/avatars/42.jpg",
  "content_type": "image/jpeg"
}
```

**What to do with these values:**
1. `signed_url` — PUT the image bytes directly to this URL (from the client, not through the backend)
2. After the PUT succeeds, call Step 2 below with `avatar_url`

---

## Avatar Upload — Step 2: Save URL

```
PATCH /profile/avatar
Authorization: Bearer <access_token>
Content-Type: application/json
```

**Request body:**
```json
{
  "avatar_url": "https://your-supabase.supabase.co/storage/v1/object/public/avatars/42.jpg"
}
```

> Use the exact `avatar_url` value returned by Step 1. The backend verifies the file actually exists in storage before saving.

**Response `data`:**
```json
{
  "avatar_url": "https://your-supabase.supabase.co/storage/v1/object/public/avatars/42.jpg"
}
```

**Errors:**

| Status | Detail | When |
|--------|--------|------|
| 400 | avatar_url does not belong to the avatars storage bucket | Wrong URL |
| 400 | Avatar image not found in storage | File PUT failed or not yet propagated |
| 503 | Storage verification temporarily unavailable | Supabase storage is down |

---

## Full Avatar Upload Flow (Flutter)

```dart
// Step 1: Get signed upload URL
final res1 = await dio.get('/profile/avatar-upload-url',
  queryParameters: {'content_type': 'image/jpeg'});
final signedUrl = res1.data['data']['signed_url'];
final avatarUrl = res1.data['data']['avatar_url'];

// Step 2: PUT image bytes directly to Supabase (no auth header here)
final bytes = await imageFile.readAsBytes();
await Dio().put(
  signedUrl,
  data: Stream.fromIterable(bytes.map((e) => [e])),
  options: Options(
    headers: {
      'Content-Type': 'image/jpeg',
      'Content-Length': bytes.length,
    },
  ),
);

// Step 3: Persist URL to our backend
await dio.patch('/profile/avatar', data: {'avatar_url': avatarUrl});
```

---

## Public Profile View

> No auth required. Use this to render another user's profile page.

```
GET /profile/{profile_id}
```

**Response `data`:**
```json
{
  "id": 42,
  "name": "Sanket Suryawanshi",
  "role_id": 1,
  "is_user_verified": true,
  "is_business_verified": false,
  "commodities": [
    { "id": 1, "name": "Rice" }
  ],
  "followers_count": 47,
  "following_count": 23,
  "posts_count": 12,
  "business_name": "Shri Balaji Global",
  "city": "Pune",
  "state": "Maharashtra",
  "latitude": 18.5204,
  "longitude": 73.8567,
  "avatar_url": "https://..."
}
```

> `phone_number`, `country_code`, and `interests` are **not** included in the public view.

**Errors:**

| Status | Detail | When |
|--------|--------|------|
| 404 | Profile not found | Invalid `profile_id` |

---

## Delete Profile

> Deletes the profile row only. The `users` row (phone/auth) stays intact.

```
DELETE /profile/
Authorization: Bearer <access_token>
```

**Response `data`:** `null` (message: "Profile deleted successfully")

---

## Delete Account (Full)

> Permanently deletes the user + profile + all associated data (sessions, posts, connections, etc.). Irreversible.

```
DELETE /profile/user
Authorization: Bearer <access_token>
```

**Response `data`:** `null` (message: "User and all associated data deleted successfully")

---

## Common Error Patterns

### 401 — Token expired
```json
{ "detail": "Access token has expired" }
```
→ Call `POST /auth/refresh` with your stored `refresh_token` to get a new access token, then retry.

### 401 — Session revoked
```json
{ "detail": "Session has been revoked" }
```
→ Session was logged out from another device or force-expired. Redirect to login screen.

---

## Data Model Cheat Sheet

### `ProfileResponse` (returned by `GET /profile/me`, `POST /profile/`, `PATCH /profile/`)
```
id                   int           — profile_id
name                 string
role_id              int           — 1=Trader  2=Broker  3=Exporter
phone_number         string        — read-only
country_code         string        — e.g. "+91"
commodities          Commodity[]   — [{id, name}]
interests            Interest[]    — [{id, name}]
is_user_verified     bool          — true after KYC (PAN/Aadhaar) passes
is_business_verified bool          — true after KYB (GST/IEC) passes
followers_count      int
following_count      int
posts_count          int
business_name        string|null
city                 string|null
state                string|null
latitude             float
longitude            float
avatar_url           string|null
```

### `ProfilePublicResponse` (returned by `GET /profile/{id}`)
```
id                   int
name                 string
role_id              int
is_user_verified     bool          — KYC badge
is_business_verified bool          — KYB badge
commodities          Commodity[]
followers_count      int
following_count      int
posts_count          int
business_name        string|null
city                 string|null
state                string|null
latitude             float
longitude            float
avatar_url           string|null
```

> `phone_number`, `country_code`, and `interests` are not exposed on the public profile.

---

## Onboarding Screen Mapping

| Screen | API call | Token used |
|--------|----------|------------|
| Phone OTP verified | `POST /auth/firebase-verify` | Firebase ID token |
| New user detected | `POST /profile/user` | Onboarding token (30 min) |
| Name + Role + Commodities + Interests + Quantity | `POST /profile/` | Onboarding token |
| Done → Home Screen | — | Access token (received in Step 2 response) |
| KYC / KYB verification (post-onboarding) | See `verification_module.md` | Access token |
| Edit profile | `PATCH /profile/` | Access token |
| Change avatar | `GET /profile/avatar-upload-url` → PUT → `PATCH /profile/avatar` | Access token |
