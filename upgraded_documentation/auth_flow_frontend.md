# Vanijyaa API — Frontend Auth & Onboarding Reference

> For Flutter developers.  
> Every request, every response, every field — exactly as the server sends it.

---

## Base URL

```
https://<your-domain>          (production)
http://localhost:8000           (local dev)
```

All responses follow this wrapper:

```json
{
  "status": "success",
  "message": "...",
  "data": { ... }
}
```

On errors:

```json
{
  "detail": "Human-readable error message"
}
```

---

## Token Quick Reference

| Token | Lifetime | What it's for |
|-------|----------|---------------|
| `onboarding_token` | 30 minutes | Only for profile creation steps (new users) |
| `access_token` | **10 hours** (36,000 seconds) | Every protected API call |
| `refresh_token` | 30 days | Getting a new `access_token` when it expires |

All tokens are sent in the `Authorization` header:

```
Authorization: Bearer <token>
```

### What's inside the access token (decoded)

```json
{
  "sub": "550e8400-e29b-41d4-a716-446655440000",
  "pid": 42,
  "jti": "session-uuid",
  "type": "access",
  "exp": 1746351600
}
```

- `sub` → `user_id` (UUID)
- `pid` → `profile_id` (int) — **both IDs are in the token**, so you never need to pass them as query params
- The server reads these from the token on every call — no extra DB lookup

---

## Flow Overview

```
NEW USER
  Firebase OTP  →  /auth/firebase-verify  →  onboarding_token
  onboarding_token  →  /profile/user
  onboarding_token  →  /profile/          →  access_token + refresh_token
                                              (onboarding done, enter the app)

RETURNING USER
  Firebase OTP  →  /auth/firebase-verify  →  access_token + refresh_token
                                              (go straight to the app)

TOKEN EXPIRED (after 10 hours)
  refresh_token  →  /auth/refresh  →  new access_token + new refresh_token

LOGOUT
  access_token  →  /auth/logout  →  session revoked
```

---

## Step-by-Step: New User Onboarding

### Step 0 — Firebase OTP (client-side, no backend call)

Use `firebase_auth` Flutter package to send and verify the OTP.  
After the user enters the correct OTP, Firebase gives you an ID token:

```dart
final userCredential = await FirebaseAuth.instance.signInWithCredential(credential);
final firebaseIdToken = await userCredential.user!.getIdToken();
```

This `firebaseIdToken` is what you send to the backend.

---

### Step 1 — Verify Firebase Token

```
POST /auth/firebase-verify
```

**Request body:**
```json
{
  "firebase_id_token": "eyJhbGciO...",
  "device_info": "Pixel 8 / Android 14"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `firebase_id_token` | string | Yes | From Firebase after OTP verify |
| `device_info` | string | No | Device name, OS version — stored for session info |

---

**Response — New user (no account exists):**
```json
{
  "status": "success",
  "message": "OTP verified. Use the onboarding token to complete registration.",
  "data": {
    "is_new_user": true,
    "onboarding_token": "eyJhbGciOiJIUzI1NiJ9...",
    "access_token": null,
    "refresh_token": null,
    "expires_in": null,
    "user_id": null,
    "profile_id": null,
    "token_type": "bearer"
  }
}
```

**Response — Returning user (account + profile exists):**
```json
{
  "status": "success",
  "message": "Welcome back.",
  "data": {
    "is_new_user": false,
    "onboarding_token": null,
    "access_token": "eyJhbGciOiJIUzI1NiJ9...",
    "refresh_token": "xK9mP2vQnR8sT4wL...",
    "expires_in": 36000,
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "profile_id": 42,
    "token_type": "bearer"
  }
}
```

**What to do in Flutter:**

```dart
if (data['is_new_user'] == true) {
  // Store onboarding_token in memory (not SharedPreferences — it's short-lived)
  // Navigate to name/role screen
  onboardingToken = data['onboarding_token'];
} else {
  // Store access_token and refresh_token in secure storage
  // Navigate to home screen
  await storage.write(key: 'access_token',  value: data['access_token']);
  await storage.write(key: 'refresh_token', value: data['refresh_token']);
}
```

**Error responses:**

| Status | detail | Meaning |
|--------|--------|---------|
| 401 | `Invalid Firebase token: ...` | Token expired or tampered |

---

### Step 2 — Create User Row

```
POST /profile/user
Authorization: Bearer <onboarding_token>
```

**Request body:** none (phone + country code are read from the token)

**Response:**
```json
{
  "status": "success",
  "message": "User created successfully",
  "data": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "phone_number": "9876543210",
    "country_code": "+91",
    "created_at": "2026-05-04T10:00:00"
  }
}
```

The `id` here is the `user_id` (UUID). You do **not** need to store it — every protected API reads identity from the JWT automatically.

**Error responses:**

| Status | detail | Meaning |
|--------|--------|---------|
| 401 | `Onboarding token has expired` | 30 min window passed, restart from Step 1 |
| 409 | `Phone number already registered` | Race condition — user already exists, go to Step 1 again |

---

### Step 3 — Create Profile (Final Onboarding Step)

```
POST /profile/
Authorization: Bearer <onboarding_token>
```

**Request body:**
```json
{
  "role_id": 1,
  "name": "Ravi Kumar",
  "commodities": [1, 2],
  "interests": [1, 3],
  "quantity_min": 100,
  "quantity_max": 5000,
  "business_name": "Kumar Agro Pvt Ltd",
  "city": "Pune",
  "state": "Maharashtra",
  "latitude": 18.5204,
  "longitude": 73.8567
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `role_id` | int | Yes | 1 = Trader, 2 = Broker, 3 = Exporter |
| `name` | string | Yes | User's display name |
| `commodities` | int[] | Yes | IDs from lookup: 1=Rice, 2=Cotton, 3=Sugar |
| `interests` | int[] | Yes | IDs from lookup: 1=Connections, 2=Leads, 3=News |
| `quantity_min` | float | Yes | Minimum trade quantity |
| `quantity_max` | float | Yes | Maximum trade quantity (must be >= min) |
| `business_name` | string | No | Company / shop name |
| `city` | string | No | City name |
| `state` | string | No | State name |
| `latitude` | float | Yes | Device GPS or selected on map |
| `longitude` | float | Yes | Device GPS or selected on map |

**Response:**
```json
{
  "status": "success",
  "message": "Profile created successfully.",
  "data": {
    "profile": {
      "id": 42,
      "name": "Ravi Kumar",
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
      "posts_count": 0,
      "business_name": "Kumar Agro Pvt Ltd",
      "city": "Pune",
      "state": "Maharashtra",
      "latitude": 18.5204,
      "longitude": 73.8567,
      "avatar_url": null
    },
    "access_token": "eyJhbGciOiJIUzI1NiJ9...",
    "refresh_token": "xK9mP2vQnR8sT4wL...",
    "token_type": "bearer",
    "expires_in": 36000
  }
}
```

**What to do in Flutter:**

```dart
// Onboarding complete — store tokens and navigate home
await storage.write(key: 'access_token',  value: data['access_token']);
await storage.write(key: 'refresh_token', value: data['refresh_token']);
// user_id and profile_id are embedded in the JWT — no need to store them separately
// Navigate to home
```

**Error responses:**

| Status | detail | Meaning |
|--------|--------|---------|
| 400 | `quantity_min cannot be greater than quantity_max` | Fix the values |
| 400 | `Invalid role_id: X. Use 1=Trader, 2=Broker, 3=Exporter.` | Wrong role |
| 400 | `Invalid commodity_ids: [X]` | Commodity ID doesn't exist |
| 401 | `Onboarding token has expired` | 30 min window passed, restart |
| 404 | `User not found — create user first via POST /profile/user` | Step 2 was skipped |
| 409 | `Profile already exists for this user` | Already created, skip to home |

---

## Token Management (Every App Session)

### Storing Tokens

Use `flutter_secure_storage` — never plain `SharedPreferences` for tokens.

```dart
const storage = FlutterSecureStorage();

// Save
await storage.write(key: 'access_token',  value: accessToken);
await storage.write(key: 'refresh_token', value: refreshToken);

// Read
final accessToken  = await storage.read(key: 'access_token');
final refreshToken = await storage.read(key: 'refresh_token');

// Delete (on logout)
await storage.delete(key: 'access_token');
await storage.delete(key: 'refresh_token');
```

---

### Refreshing the Access Token (After 10 Hours)

```
POST /auth/refresh
```

**Request body:**
```json
{
  "refresh_token": "xK9mP2vQnR8sT4wL..."
}
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiJ9...",
  "refresh_token": "nT7pQ3rS1kU6mV9w...",
  "token_type": "bearer",
  "expires_in": 36000
}
```

> **Important:** The refresh token is **rotated** on every call — the old one is
> dead immediately. Always save both the new `access_token` AND the new
> `refresh_token` from this response.

**Error responses:**

| Status | detail | Meaning |
|--------|--------|---------|
| 401 | `Invalid or revoked refresh token.` | Token was used already or session was logged out |
| 401 | `Refresh token has expired. Please sign in again.` | 30-day window passed — force re-login |

---

### Implementing Auto-Refresh in Flutter (Dio Interceptor)

Set this up once in your Dio client. It silently refreshes the token in the
background whenever any API call returns a 401, then retries the original
request automatically.

```dart
import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class AuthInterceptor extends Interceptor {
  final Dio dio;
  final FlutterSecureStorage storage;
  bool _isRefreshing = false;

  AuthInterceptor(this.dio, this.storage);

  @override
  void onRequest(RequestOptions options, RequestInterceptorHandler handler) async {
    final token = await storage.read(key: 'access_token');
    if (token != null) {
      options.headers['Authorization'] = 'Bearer $token';
    }
    handler.next(options);
  }

  @override
  void onError(DioException err, ErrorInterceptorHandler handler) async {
    if (err.response?.statusCode == 401 && !_isRefreshing) {
      _isRefreshing = true;
      try {
        final refreshToken = await storage.read(key: 'refresh_token');
        if (refreshToken == null) {
          _forceLogout();
          return handler.next(err);
        }

        // Call refresh endpoint
        final refreshDio = Dio(); // separate instance — no interceptor loop
        final resp = await refreshDio.post(
          '$baseUrl/auth/refresh',
          data: {'refresh_token': refreshToken},
        );

        final newAccess  = resp.data['access_token']  as String;
        final newRefresh = resp.data['refresh_token'] as String;

        // Save new tokens
        await storage.write(key: 'access_token',  value: newAccess);
        await storage.write(key: 'refresh_token', value: newRefresh);

        // Retry the original request with the new token
        final opts = err.requestOptions;
        opts.headers['Authorization'] = 'Bearer $newAccess';
        final retryResp = await dio.fetch(opts);
        return handler.resolve(retryResp);

      } catch (_) {
        _forceLogout(); // refresh itself failed — send user back to login
      } finally {
        _isRefreshing = false;
      }
    }
    handler.next(err);
  }

  void _forceLogout() async {
    await storage.deleteAll();
    // Navigate to login screen using your router
  }
}
```

---

## Logout

```
POST /auth/logout
Authorization: Bearer <access_token>
```

**Request body:** empty `{}`

**Response:**
```json
{
  "status": "success",
  "message": "Logged out successfully.",
  "data": null
}
```

After this call, delete both tokens from storage and navigate to the login screen.

```dart
Future<void> logout() async {
  try {
    await dio.post('/auth/logout'); // interceptor adds the Bearer header
  } catch (_) {
    // ignore errors — delete tokens regardless
  }
  await storage.deleteAll();
  // Navigate to login
}
```

---

## App Startup — Should I Show Login or Home?

```dart
Future<void> checkAuthOnStartup() async {
  final accessToken  = await storage.read(key: 'access_token');
  final refreshToken = await storage.read(key: 'refresh_token');

  if (accessToken == null || refreshToken == null) {
    // No tokens — go to login
    navigateToLogin();
    return;
  }

  // Tokens exist — let the Dio interceptor handle any refresh automatically.
  // Try a lightweight API call to verify things are working.
  try {
    await api.getMyProfile();
    navigateToHome();
  } on ForceLogoutException {
    navigateToLogin(); // refresh token expired (30 days) — must re-login
  }
}
```

---

## Complete Endpoint List

### Auth Endpoints

| Method | Endpoint | Auth Required | Purpose |
|--------|----------|---------------|---------|
| POST | `/auth/firebase-verify` | None | Exchange Firebase OTP token |
| POST | `/auth/refresh` | None (refresh token in body) | Rotate access token |
| POST | `/auth/logout` | `access_token` | Revoke session |

### Profile Endpoints

| Method | Endpoint | Auth Required | Notes |
|--------|----------|---------------|-------|
| POST | `/profile/user` | `onboarding_token` | Onboarding step 1 — create user row |
| POST | `/profile/` | `onboarding_token` | Onboarding step 2 — create profile, returns token pair |
| GET | `/profile/me` | `access_token` | Get your own full profile |
| PATCH | `/profile/` | `access_token` | Update your profile |
| PATCH | `/profile/user/fcm-token` | `access_token` | Update push notification token |
| GET | `/profile/avatar-upload-url` | `access_token` | Get signed URL to upload avatar |
| PATCH | `/profile/avatar` | `access_token` | Save avatar URL after upload |
| DELETE | `/profile/` | `access_token` | Delete your profile |
| DELETE | `/profile/user` | `access_token` | Delete your account entirely |
| GET | `/profile/{profile_id}` | None | View any user's public profile |

### Verification Endpoints

> KYC / KYB document verification has its own module. See `verification_module.md`.

| Method | Endpoint | Auth Required | Purpose |
|--------|----------|---------------|---------|
| POST | `/verification/kyc/pan` | `access_token` | Verify PAN card (KYC) |
| POST | `/verification/kyc/aadhaar` | `access_token` | Verify Aadhaar — 501, not yet available |
| POST | `/verification/kyb/gst` | `access_token` | Verify GST — Traders & Brokers only |
| POST | `/verification/kyb/iec` | `access_token` | Verify IEC — Exporters only |
| GET | `/verification/status` | `access_token` | Get current KYC + KYB status |

> **No query params for identity.** Every protected endpoint reads `user_id` and `profile_id` directly
> from the JWT — you never pass them in the URL. The only thing you send is the `Authorization: Bearer` header.

---

## Lookup Table IDs

These IDs are fixed and will not change.

**Roles** (use in `role_id`):

| ID | Name |
|----|------|
| 1 | Trader |
| 2 | Broker |
| 3 | Exporter |

**Commodities** (use in `commodities: [...]`):

| ID | Name |
|----|------|
| 1 | Rice |
| 2 | Cotton |
| 3 | Sugar |

**Interests** (use in `interests: [...]`):

| ID | Name |
|----|------|
| 1 | Connections |
| 2 | Leads |
| 3 | News |

---

## Error Handling Cheat Sheet

| HTTP Status | When it happens | What to do |
|-------------|----------------|------------|
| 400 | Bad request payload | Show validation error to user |
| 401 | Token expired / invalid | Run token refresh; if refresh fails, force logout |
| 404 | Resource not found | Show error UI |
| 409 | Conflict (duplicate user/profile) | Handle gracefully — usually safe to skip the step |
| 429 | Too many requests | Back off and retry after the `Retry-After` header value |
| 500 | Server error | Show generic error, retry |

---

## Token Lifetime Summary

```
Access token:   600 minutes  =  10 hours   =  36,000 seconds
Refresh token:  30 days      =  720 hours  =  2,592,000 seconds
Onboarding:     30 minutes   =             =  1,800 seconds
```
