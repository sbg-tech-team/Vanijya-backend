# Verification Build Changes

This document records every change made when extracting the verification logic into its own module.

---

## Auth Module — Changes

### `app/modules/auth/service.py`
**Removed:**
- `sandbox_base_url` constant
- `_sandbox_token` variable
- `_get_sandbox_token()` function
- `_auth_sandbox_api()` function
- `_verify_pan_card()` function (moved to verification module)
- `_verify_gst_number()` function (moved to verification module)
- `import requests`

### `app/modules/auth/schemas.py`
**Removed:**
- `PanVerificationRequest` class
- `GstVerificationRequest` class

### `app/modules/auth/router.py`
**Removed endpoints:**
- `POST /auth/verify-pan`
- `POST /auth/get-gst-details`

**Removed imports:**
- `_verify_pan_card`, `_verify_gst_number` from service
- `PanVerificationRequest`, `GstVerificationRequest` from schemas

---

## Profile Module — Changes

### `app/modules/profile/models.py`
**Removed:**
- `Profile_Document` class (entire ORM model — the `profile_documents` table is dropped by migration)
- `documents` relationship on `Profile`
- `is_verified: Mapped[bool]` column on `Profile`

**Kept:**
- `is_user_verified: Mapped[bool]` — set to `true` by verification module after KYC passes
- `is_business_verified: Mapped[bool]` — set to `true` by verification module after KYB passes

### `app/modules/profile/schemas.py`
**Removed:**
- `VerifyProfileRequest` class
- `DocumentSubmit` class
- `VALID_IDENTITY_TYPES` constant
- `VALID_BUSINESS_TYPES` constant
- `is_verified` field from `ProfileResponse`
- `is_verified` field from `ProfilePublicResponse`

**Added to both `ProfileResponse` and `ProfilePublicResponse`:**
- `is_user_verified: bool`
- `is_business_verified: bool`

### `app/modules/profile/service.py`
**Removed:**
- `submit_verification()` function
- Imports: `Profile_Document`, `VerifyProfileRequest`, `VALID_IDENTITY_TYPES`, `VALID_BUSINESS_TYPES`

**Updated:**
- `_to_response()` — uses `is_user_verified` / `is_business_verified` instead of `is_verified`
- `get_profile_by_id()` — same replacement

### `app/modules/profile/router.py`
**Removed endpoint:**
- `POST /profile/verify`

**Removed imports:**
- `VerifyProfileRequest` from schemas
- `submit_verification` from service

---

## Verification Module — Created (New)

### `app/modules/verification/__init__.py`
Empty file — marks the directory as a Python package.

### `app/modules/verification/models.py`
New `VerificationRecord` ORM model replacing `profile_documents`:

| Column | Type | Notes |
|--------|------|-------|
| `id` | int (PK, autoincrement) | |
| `profile_id` | int (FK → profile.id, CASCADE) | |
| `document_type` | str(10) | `"pan"` / `"aadhaar"` / `"gst"` / `"iec"` |
| `document_number` | str(100) | The actual document number submitted |
| `verification_category` | str(5) | `"kyc"` or `"kyb"` |
| `status` | str(20) | `"verified"` / `"error"` |
| `api_provider` | str(50) | `"surepass"` / `"placeholder"` |
| `api_response` | JSON | Full external API response stored for audit trail |
| `error_message` | str(500, nullable) | Set when status is `"error"` |
| `verified_at` | DateTime (nullable) | Timestamp of successful verification |
| `created_at` | DateTime | |
| `updated_at` | DateTime | |

Unique constraint on `(profile_id, document_type)` — one record per document type per user. Re-submissions overwrite rather than duplicate.

### `app/modules/verification/schemas.py`
New request and response schemas:

| Class | Purpose |
|-------|---------|
| `PanVerifyRequest` | `id_number`, `name`, `dob` |
| `AadhaarVerifyRequest` | `aadhaar_number` (placeholder, 501) |
| `GstVerifyRequest` | `gstin` |
| `IecVerifyRequest` | `iec_number` |
| `VerificationDocStatus` | `status`, `document_type`, `verified_at` |
| `VerificationStatusResponse` | `kyc: VerificationDocStatus`, `kyb: VerificationDocStatus` |

### `app/modules/verification/service.py`
Surepass integration and orchestration logic.

**External API functions (all call `sandbox.surepass.io/api/v1` or production URL via env var):**
- `_verify_pan_surepass(id_number, name, dob)` — two-gate: `success: true` AND `pan_status` contains `"EXISTING AND VALID"`
- `_verify_gst_surepass(gstin)` — two-gate: `success: true` AND `gstin_status == "Active"`
- `_verify_iec_surepass(iec_number)` — two-gate: `success: true` AND `personal_details.iec_status == "Valid"`
- `_verify_aadhaar(aadhaar_number)` — raises `NotImplementedError` (API provider TBD)

**Two-gate validation** (applied to all three live documents): the external API returning `success: true` only means the HTTP call worked — it does not mean the document is valid. A separate document-status field is always checked.

**Core functions:**
- `verify_document(db, profile, document_type, document_number, **api_kwargs)` — enforces KYC-before-KYB rule, enforces role-based KYB document routing, calls the appropriate API function, upserts the `VerificationRecord`, and updates `profile.is_user_verified` or `profile.is_business_verified` on success
- `get_verification_status(db, profile_id)` — returns current KYC and KYB status from `verification_records`

**Role-based KYB document routing:**

| role_id | Role | Required KYB doc |
|---------|------|-----------------|
| 1 | Trader | GST |
| 2 | Broker | GST |
| 3 | Exporter | IEC |

Submitting the wrong document for a role returns 400 before any external API is called.

### `app/modules/verification/router.py`
Five endpoints, all requiring `access_token`:

| Method | Endpoint | Behaviour |
|--------|----------|-----------|
| POST | `/verification/kyc/pan` | Live — calls Surepass |
| POST | `/verification/kyc/aadhaar` | HTTP 501 placeholder |
| POST | `/verification/kyb/gst` | Live — calls Surepass |
| POST | `/verification/kyb/iec` | Live — calls Surepass |
| GET | `/verification/status` | Returns KYC + KYB status |

---

## Infrastructure Changes

### `main.py`
- Added `from app.modules.verification.router import router as verification_router`
- Added `app.include_router(verification_router)`

### `alembic/env.py`
- Removed `Profile_Document` from profile models import
- Added `from app.modules.verification.models import VerificationRecord`

### `alembic/versions/d0e1f2a3b4c5_create_verification_module.py` (new migration)
**`upgrade()`:**
- Drops `profile_documents` table
- Drops `is_verified` column from `profile`
- Creates `verification_records` table

**`downgrade()`:** reverses all three steps.

### `.env`
**Added:**
```
SUREPASS_BASE_URL=https://sandbox.surepass.io/api/v1
SUREPASS_TOKEN=<sandbox token>
```
**Removed:** `X-API-KEY`, `X-API-SECRET` (Sandbox.co.in credentials, no longer used)

---

## Test Script Created

### `scripts/test_verification.py`
Calls `_verify_pan_surepass`, `_verify_gst_surepass`, `_verify_iec_surepass` directly without FastAPI or auth tokens. Loads `.env` via `python-dotenv`. Used for backend-only API testing.

---

## Documentation Changes

| File | Change |
|------|--------|
| `upgraded_documentation/verification_module.md` | **Created** — full reference for all 5 verification endpoints, role/document mapping, status values, frontend usage guide |
| `upgraded_documentation/profile_apis_frontend.md` | **Updated** — removed `POST /profile/verify` section and quick reference entry; removed `is_verified`; added `is_user_verified` / `is_business_verified` throughout; updated both data model cheat sheets; added pointer to `verification_module.md` |
| `upgraded_documentation/auth_flow_frontend.md` | **Updated** — removed `POST /profile/verify` from complete endpoint list; added verification endpoints table with pointer to `verification_module.md`; removed `is_verified` from profile creation response example |
| `upgraded_documentation/auth_flow.md` | No changes required — was already clean |

---

## Verification Flags — Before and After

| | Before | After |
|---|--------|-------|
| Profile column | `is_verified` (combined) | `is_user_verified` + `is_business_verified` (separate) |
| Set by | Profile module (`submit_verification`) | Verification module (`verify_document`) |
| Storage | `profile_documents` table | `verification_records` table (with full API response JSON) |
| API integration | None — document was just stored | Real-time Surepass API call in the same request |
| Audit trail | Document file paths only | Full Surepass JSON response per attempt |
| Re-submission | Created duplicate rows | Overwrites existing record for that document type |
