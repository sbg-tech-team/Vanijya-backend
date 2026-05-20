# Vanijyaa API — Verification Module Reference

> For Flutter developers.  
> Covers KYC (identity) and KYB (business) verification — all endpoints, all responses, all rules.

---

## Overview

Verification is split into two independent layers:

| Layer | Full Form | What it proves | Documents accepted |
|-------|-----------|----------------|--------------------|
| **KYC** | Know Your Customer | Who the person is | PAN card, Aadhaar |
| **KYB** | Know Your Business | That the business is real | GST certificate (Traders & Brokers), IEC code (Exporters) |

**Rule: KYC must be completed before KYB is allowed.**  
The backend will reject a KYB request if `is_user_verified` is still `false`.

---

## Role → Document Mapping

| Role | role_id | KYC (choose one) | KYB (required) |
|------|---------|-------------------|----------------|
| Trader | 1 | PAN or Aadhaar | GST |
| Broker | 2 | PAN or Aadhaar | GST |
| Exporter | 3 | PAN or Aadhaar | IEC |

If a Trader/Broker submits IEC, or an Exporter submits GST — the backend returns a 400 error immediately without calling any external API.

---

## How Verification Works (Internal Flow)

```
User submits document
  → Backend validates role + KYC-first rule
  → Calls Surepass API with document details
  → Checks both:
      (a) API success flag (did the call work?)
      (b) Document status field (is the document genuinely valid?)
  → Saves full API response to verification_records table
  → If valid: sets is_user_verified or is_business_verified on profile
  → Returns result to client
```

Every attempt — pass or fail — is stored in `verification_records` with the full API response, so there is a complete audit trail.

---

## Verification Status on Profile

After successful verification, two boolean flags are set on the user's profile:

| Flag | Set when | Visible on |
|------|----------|------------|
| `is_user_verified` | KYC (PAN / Aadhaar) passes | All profile responses |
| `is_business_verified` | KYB (GST / IEC) passes | All profile responses |

These flags are what the frontend uses to show verification badges. The profile module exposes them — the verification module writes them.

---

## Base URL

```
https://<your-domain>          (production)
http://localhost:8000           (local dev)
```

All responses:
```json
{
  "status": "success",
  "message": "...",
  "data": { ... }
}
```

All errors:
```json
{
  "detail": "Human-readable error message"
}
```

All verification endpoints require an **access token**:
```
Authorization: Bearer <access_token>
```

---

## Endpoints

---

### POST `/verification/kyc/pan`

Verify a PAN card for identity (KYC).

**Request:**
```json
{
  "id_number": "ABCDE1234F",
  "name": "Ravi Kumar",
  "dob": "1990-07-15"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id_number` | string | Yes | PAN number |
| `name` | string | Yes | Name as it appears on the PAN |
| `dob` | string | Yes | Date of birth in `YYYY-MM-DD` format |

**What the backend checks:**
1. Surepass API call succeeds (`success: true`)
2. `pan_status` contains `"EXISTING AND VALID"` — a PAN that exists in the database but is inactive or cancelled will still fail this check

**Success response:**
```json
{
  "status": "success",
  "message": "PAN verification complete.",
  "data": {
    "document_type": "pan",
    "status": "verified",
    "verified_at": "2026-05-20T10:30:00"
  }
}
```

**Effect:** `profile.is_user_verified` is set to `true`.

**Error responses:**

| Status | detail | Cause |
|--------|--------|-------|
| 400 | `PAN is not valid: NOT-EXISTING AND INVALID` | PAN number does not exist |
| 400 | `PAN verification failed: <Surepass message>` | API call failed |
| 404 | `Profile not found. Complete onboarding first.` | Profile not created yet |

---

### POST `/verification/kyc/aadhaar`

> **Status: Not yet available.**  
> API provider for Aadhaar is not yet decided.

**Response:**
```json
{
  "detail": "Aadhaar verification is not yet available. API provider TBD."
}
```
HTTP status: `501 Not Implemented`

---

### POST `/verification/kyb/gst`

Verify a GST certificate for business verification (KYB).  
**Only for Traders (role_id=1) and Brokers (role_id=2).**

**Prerequisite:** `is_user_verified` must be `true` (KYC done first).

**Request:**
```json
{
  "gstin": "27AABCU9603R1Z5"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `gstin` | string | Yes | 15-character GST Identification Number |

**What the backend checks:**
1. User's role is Trader or Broker (not Exporter)
2. `is_user_verified == true`
3. Surepass API call succeeds (`success: true`)
4. `gstin_status == "Active"` — an inactive or cancelled GST will fail

**Success response:**
```json
{
  "status": "success",
  "message": "GST verification complete.",
  "data": {
    "document_type": "gst",
    "status": "verified",
    "verified_at": "2026-05-20T10:35:00"
  }
}
```

**Effect:** `profile.is_business_verified` is set to `true`.

**Error responses:**

| Status | detail | Cause |
|--------|--------|-------|
| 400 | `Complete identity verification (KYC) before verifying your business.` | KYC not done yet |
| 400 | `Trader must use 'gst' for business verification, not 'iec'.` | Wrong document for role |
| 400 | `GST is not active: <status>` | GSTIN exists but is cancelled/inactive |
| 400 | `GST verification failed: Invalid GSTIN` | GSTIN does not exist |
| 404 | `Profile not found. Complete onboarding first.` | Profile not created yet |

---

### POST `/verification/kyb/iec`

Verify an IEC (Import Export Code) for business verification (KYB).  
**Only for Exporters (role_id=3).**

**Prerequisite:** `is_user_verified` must be `true` (KYC done first).

**Request:**
```json
{
  "iec_number": "AABCU9603R"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `iec_number` | string | Yes | 10-character IEC code issued by DGFT |

**What the backend checks:**
1. User's role is Exporter
2. `is_user_verified == true`
3. Surepass API call succeeds (`success: true`)
4. `personal_details.iec_status == "Valid"` — an invalid or surrendered IEC will fail

**Success response:**
```json
{
  "status": "success",
  "message": "IEC verification complete.",
  "data": {
    "document_type": "iec",
    "status": "verified",
    "verified_at": "2026-05-20T10:40:00"
  }
}
```

**Effect:** `profile.is_business_verified` is set to `true`.

**Error responses:**

| Status | detail | Cause |
|--------|--------|-------|
| 400 | `Complete identity verification (KYC) before verifying your business.` | KYC not done yet |
| 400 | `Exporter must use 'iec' for business verification, not 'gst'.` | Wrong document for role |
| 400 | `IEC is not valid: <status>` | IEC exists but is not valid |
| 400 | `IEC verification failed: Invalid IEC Number.` | IEC does not exist |
| 404 | `Profile not found. Complete onboarding first.` | Profile not created yet |

---

### GET `/verification/status`

Get the current KYC and KYB verification status for the logged-in user.  
Use this on the verification management screen.

**Request:** No body. Access token required.

**Response:**
```json
{
  "status": "success",
  "message": "...",
  "data": {
    "kyc": {
      "status": "verified",
      "document_type": "pan",
      "verified_at": "2026-05-20T10:30:00"
    },
    "kyb": {
      "status": "not_submitted",
      "document_type": null,
      "verified_at": null
    }
  }
}
```

**`status` values:**

| Value | Meaning |
|-------|---------|
| `"verified"` | Document passed all checks — flag is set on profile |
| `"error"` | Submitted but failed (wrong number, inactive document etc.) |
| `"not_submitted"` | Never attempted |

---

## Frontend Usage Guide

### Verification screen (user manages their own KYC/KYB)

```
GET /verification/status
  → Show KYC section with status
  → If kyc.status == "not_submitted" or "error" → show PAN/Aadhaar form
  → If kyc.status == "verified" → show green badge, unlock KYB section

  → Show KYB section (only if kyc is verified)
  → Role 1/2 → show GST form
  → Role 3   → show IEC form
  → If kyb.status == "verified" → show green badge
```

### Showing badges on profile cards (your own profile or others)

Read `is_user_verified` and `is_business_verified` from any profile response:

```
GET /profile/me          → your own profile
GET /profile/{id}        → any public profile
```

```dart
if (profile['is_user_verified'] == true) {
  // show KYC badge (identity verified)
}
if (profile['is_business_verified'] == true) {
  // show KYB badge (business verified)
}
```

---

## Re-submission Behaviour

If a user submits the same document type again (e.g., PAN after a failed attempt), the existing record in `verification_records` is **overwritten** — not duplicated. The latest attempt always wins. Profile flags are only updated when the new attempt also passes.

---

## Complete Endpoint Summary

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| POST | `/verification/kyc/pan` | `access_token` | Verify PAN card (KYC) |
| POST | `/verification/kyc/aadhaar` | `access_token` | Verify Aadhaar — **501, not yet available** |
| POST | `/verification/kyb/gst` | `access_token` | Verify GST — Traders & Brokers only |
| POST | `/verification/kyb/iec` | `access_token` | Verify IEC — Exporters only |
| GET | `/verification/status` | `access_token` | Get KYC + KYB status for current user |

---

## Error Handling Cheat Sheet

| HTTP Status | When | What to do |
|-------------|------|------------|
| 400 | Document invalid, wrong role, KYC not done | Show specific error message to user |
| 401 | Token expired | Run token refresh (same as all other endpoints) |
| 404 | Profile not found | User hasn't completed onboarding — redirect |
| 501 | Aadhaar endpoint | Show "Coming soon" in UI |

---

## Lookup: Role → Required Documents

```
role_id = 1 (Trader)   → KYC: PAN or Aadhaar  +  KYB: GST
role_id = 2 (Broker)   → KYC: PAN or Aadhaar  +  KYB: GST
role_id = 3 (Exporter) → KYC: PAN or Aadhaar  +  KYB: IEC
```
