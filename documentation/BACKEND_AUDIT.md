# Vanijyaa Backend — Full Security & Reliability Audit

> **Audit date:** 2026-04-23  
> **Auditor role:** Senior Backend Architect + QA + Reliability Engineer  
> **Scope:** Every Python file in `backend/` — models, schemas, routers, services, core, tasks, migrations  
> **Status:** PHASE 1 COMPLETE — listing only, no fixes applied yet  
> **Phase 2 (2026-05-12):** BUG-001, BUG-002, BUG-003, BUG-005 resolved — see fix notes inline below.

---

## Executive Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 8 |
| HIGH | 9 |
| MEDIUM | 14 |
| LOW | 6 |
| **Total** | **37** |

The most dangerous issues are a **system-wide authentication bypass** (every endpoint except `/auth/firebase-verify` and `/profile/user` accepts user identity from an unvalidated query param or URL path), combined with **plaintext secret storage**, **no JWT expiry**, and **live credentials committed to git**.

---

## BUG LIST

---

### BUG-001 ✅ FIXED (2026-05-12)
**Category:** Authentication / Authorization  
**File:** `app/modules/profile/router.py` — all endpoints except `POST /profile/user` and `POST /profile/`  
**Severity:** CRITICAL  
**Short explanation:** Every authenticated profile action (`GET /me`, `PATCH /`, `PATCH /avatar`, `POST /verify`, `PATCH /user/fcm-token`, `DELETE /user`, `DELETE /`) accepts `user_id` as a plain `Query(...)` parameter with zero token validation. Any caller who knows another user's UUID can read, modify, or delete their profile.  
**Root cause:** Auth dependency (`get_current_user_id`) exists in `dependencies.py` but is only wired up for the two onboarding endpoints. Every other endpoint uses `user_id: UUID = Query(...)` directly.  
**User impact:** Complete account takeover — read PII, change avatar, delete any account, hijack FCM token for notification spoofing.  
**Fix:** All post-registration profile endpoints now use `cu: CurrentUser = Depends(get_current_user)`. Identity comes from JWT `sub`+`pid` claims — no query param accepted.

---

### BUG-002 ✅ FIXED (2026-05-12)
**Category:** Authentication / Authorization  
**File:** `app/modules/post/router.py` — ALL endpoints  
**Severity:** CRITICAL  
**Short explanation:** Every post endpoint (`POST /posts/`, `PATCH /posts/{id}`, `DELETE /posts/{id}`, likes, comments, saves, shares) accepts `profile_id: int = Query(...)` with no verification that the caller owns that profile. Any user can post, like, comment, or delete as any other user.  
**Root cause:** No auth dependency wired in the post router. `profile_id` is treated as trusted input.  
**User impact:** Content fraud, impersonation, mass deletion of any user's posts.  
**Fix:** All 15 post router endpoints now use `profile_id: int = Depends(get_current_profile_id)`. `profile_id` is read from the JWT `pid` claim — client cannot pass a different value.

---

### BUG-003 ✅ FIXED (2026-05-12)
**Category:** Authentication / Authorization  
**File:** `app/modules/connections/router.py` — ALL endpoints  
**Severity:** CRITICAL  
**Short explanation:** Follow, unfollow, send message request, withdraw, accept, decline, search — all accept `user_id` from the URL path without validating a token. Anyone can follow/unfollow or accept message requests on behalf of any user.  
**Root cause:** Router docstring explicitly states: _"No auth token required — user_id is passed in the URL path."_  
**User impact:** Social graph manipulation, unwanted follows, accepting/declining requests on behalf of victims.  
**Fix:** Full router rewrite. Old `/{user_id}/follow/{target_id}` path pattern removed. New paths: `/follow/{target_id}`, `/message-request/{target_id}`, etc. Acting user derived from `me: UUID = Depends(get_current_user_id)` in every mutating endpoint. Public read endpoints (`/{user_id}/followers`, `/search/suggestions`) remain open.

---

### BUG-004
**Category:** Authentication / Authorization  
**File:** `app/modules/chat/presentation/router.py` and `ws_router.py` — ALL endpoints  
**Severity:** CRITICAL  
**Short explanation:** All chat REST endpoints (list conversations, open chat, send message, accept/decline, mark read, group messages) use `user_id: UUID` from the URL path. The WebSocket endpoint `GET /ws/chat/{user_id}` accepts a raw UUID with no token. Any attacker can impersonate any user in chat and read all their private messages.  
**Root cause:** No `Depends(get_current_user_id)` anywhere in the chat routers.  
**User impact:** Full read/write access to any user's private and group conversations.

---

### BUG-005 ✅ FIXED (2026-05-12)
**Category:** Authentication / Authorization  
**File:** `app/modules/groups/router.py` — ALL endpoints  
**Severity:** CRITICAL  
**Short explanation:** All group management endpoints accept `user_id: UUID = Query(...)`. An attacker can create groups as another user, add/remove members, freeze users, or delete groups they don't own.  
**Root cause:** Router comment: _"No auth token required — caller passes ?user_id=<uuid>"_  
**User impact:** Group hijacking, unauthorized member management, reputation damage.  
**Fix:** All group endpoints use `user_id: UUID = Depends(get_current_user_id)`. `GET /suggestions/{user_id}` (path param) removed and replaced with `GET /suggestions` (identity from token). Feed/news routers similarly updated.

---

### BUG-006
**Category:** Security — Secrets in Version Control  
**File:** `backend/.env`  
**Severity:** CRITICAL  
**Short explanation:** The `.env` file contains live production credentials committed to the repository: Supabase database password, JWT signing secret, Gemini API key, and Supabase service role JWT (which grants admin DB access). These are active, not rotated.  
**Root cause:** `.env` not listed in `.gitignore` or secret scanning was never configured.  
**User impact:** Full database compromise, JWT forgery for any user, cloud storage takeover, API quota theft.

---

### BUG-007
**Category:** Security — Token Storage  
**File:** `app/modules/profile/models.py:25`  
**Severity:** CRITICAL  
**Short explanation:** `User.access_token` stores Firebase/app access tokens in plaintext in the `users` table column (`String(2000)`). A DB read or SQL injection would yield usable tokens.  
**Root cause:** Architectural decision to cache tokens server-side without encryption.  
**User impact:** Stolen tokens can be used to impersonate users in Firebase-authenticated flows.

---

### BUG-008
**Category:** Configuration / Crash  
**File:** `app/modules/auth/service_msg91.py:27,37,38`  
**Severity:** CRITICAL  
**Short explanation:** `service_msg91.py` references `settings.DEV_MODE`, `settings.MSG91_AUTH_KEY`, and `settings.MSG91_TEMPLATE_ID`, but none of these fields exist in the `Settings` class in `app/core/config.py`. Any call to `send_otp()` or `verify_otp()` will raise `AttributeError` and crash with HTTP 500.  
**Root cause:** Settings class was not updated when MSG91 code was written. The file is currently dead code since auth was migrated to Firebase, but it will crash if ever called.  
**User impact:** Immediate 500 error if OTP endpoints are invoked; server crash in some configurations.

---

### BUG-009
**Category:** Authentication / Authorization  
**File:** `app/core/security/jwt_handler.py:27-30`  
**Severity:** HIGH  
**Short explanation:** `create_access_token()` issues JWTs with **no expiry** (`exp` claim is absent). The function comment reads: _"Issues a lifetime access token (no expiry — MVP mode)"_. Stolen tokens are valid forever.  
**Root cause:** Deliberate MVP shortcut not tracked for removal.  
**User impact:** Compromised token = permanent account access. No revocation path exists.

---

### BUG-010
**Category:** Data Integrity / Race Condition  
**File:** `app/modules/post/service.py:225-254` (`toggle_like`)  
**Severity:** HIGH  
**Short explanation:** The like toggle pattern is: SELECT existing → DELETE or INSERT → UPDATE counter. Under concurrent requests (two simultaneous likes), both threads may see `existing = None`, both insert a `PostLike`, and `like_count` is incremented twice. Although `PostLike` has `UniqueConstraint("post_id", "profile_id")`, the counter update runs before the constraint fires, so the count ends up inconsistent.  
**Root cause:** Non-atomic check-then-act pattern. The DB unique constraint protects the `PostLike` row but not the denormalized `like_count`.  
**User impact:** `like_count` becomes permanently incorrect; shown to all users.

---

### BUG-011
**Category:** Data Integrity / Race Condition  
**File:** `app/modules/post/service.py:351-378` (`toggle_save`)  
**Severity:** HIGH  
**Short explanation:** Same race condition as BUG-010 on the save toggle. `PostSave` has a unique constraint but the `save_count` counter update is non-atomic.  
**Root cause:** Same pattern as BUG-010.  
**User impact:** `save_count` corruption; incorrect signals fed into the recommendation engine.

---

### BUG-012
**Category:** Transaction Integrity  
**File:** `app/modules/profile/service.py:284-323` (`create_profile`)  
**Severity:** HIGH  
**Short explanation:** `create_profile` does two separate commits: first at line 311 (profile + commodities + interests), then `_upsert_user_embedding()` + commit at line 315. If `_upsert_user_embedding()` raises (e.g., `TypeError` from `int(None)` when `quantity_min` is null, `float()` call on None), the outer `except Exception: db.rollback(); raise` will roll back the second commit but the first is already durable. Profile is left without a user embedding, breaking recommendation features silently.  
**Root cause:** Two-commit design inside a single exception handler.  
**User impact:** New users invisible in connection recommendations; no error surfaced to caller.

---

### BUG-013
**Category:** Performance / N+1 Queries  
**File:** `app/modules/post/service.py:37-38` (`_active_profile_ids`)  
**Severity:** HIGH  
**Short explanation:** `_active_profile_ids()` fetches **every profile ID in the database** on every single post read (`get_post`, `get_feed`, `get_saved_posts`, `_get_post_or_raise`). This unbounded `SELECT id FROM profile` is called inside a feed fetch that may itself return 20 posts — meaning 20+ full table scans per feed request. At 10,000 profiles this becomes tens of MB of data transferred per API call.  
**Root cause:** The function was designed as a soft-delete filter but never uses joins.  
**User impact:** Severe latency degradation as user base grows; eventual timeout failures.

---

### BUG-014
**Category:** Performance / N+1 Queries  
**File:** `app/modules/post/service.py:55-78` (`_to_post_response`)  
**Severity:** HIGH  
**Short explanation:** `_to_post_response()` calls `_is_liked()` and `_is_saved()` — each a separate `SELECT` — for every single post. A feed of 20 posts issues 40 extra queries. Combined with `_active_profile_ids()` (BUG-013), a single `/posts/` request can hit the database 60+ times.  
**Root cause:** Per-post lazy lookups not batched.  
**User impact:** Feed API latency grows linearly with page size; likely exceeds acceptable response times at real load.

---

### BUG-015
**Category:** Performance / N+1 Queries  
**File:** `app/modules/groups/service.py:244-249` (`list_groups`)  
**Severity:** HIGH  
**Short explanation:** `list_groups()` fetches a page of groups then calls `_get_membership(db, g.id, user_id)` in a Python loop — one query per group. For a page of 20 groups, 20 separate `SELECT` queries fire against `group_members`.  
**Root cause:** Membership context not loaded as part of the initial query.  
**User impact:** Groups list endpoint is O(n) in DB queries; slow under load.

---

### BUG-016
**Category:** Data Integrity  
**File:** `app/modules/post/service.py:37-38` (`_active_profile_ids`)  
**Severity:** HIGH  
**Short explanation:** `_active_profile_ids()` returns ALL profile IDs including those belonging to soft-deleted users (`User.is_deleted = True`). Posts by deleted users remain visible in the feed and can be liked/commented on.  
**Root cause:** Query does not join `User` table to filter `is_deleted = False`.  
**User impact:** Deleted users' content persists in feeds; violated user expectation that deletion removes content.

---

### BUG-017
**Category:** Validation / Data Integrity  
**File:** `app/modules/profile/service.py:342`  
**Severity:** MEDIUM  
**Short explanation:** `if qmin and qmax and qmin > qmax:` — this condition is falsy when `qmin == 0` or `qmax == 0` because `0` is falsy in Python. A profile update setting `quantity_min=5, quantity_max=0` passes validation silently and persists invalid data.  
**Root cause:** Python truthiness check instead of `is not None` guard.  
**User impact:** Invalid quantity ranges stored; vector embeddings computed with inverted values; recommendation quality degraded.

---

### BUG-018
**Category:** Crash / Unhandled Exception  
**File:** `app/modules/profile/service.py:383`  
**Severity:** MEDIUM  
**Short explanation:** `assert profile_resp is not None` is a bare `assert` in production code inside `update_profile`. Python `assert` is stripped when running with `-O` (optimized mode), and in any case raises `AssertionError` (not `HTTPException`) which FastAPI converts to a 500 with no detail message.  
**Root cause:** Debug assertion left in production path.  
**User impact:** Opaque 500 on a rare but real code path; no diagnostic information returned.

---

### BUG-019
**Category:** Security — Country Code Parsing  
**File:** `app/modules/auth/service.py:63-65`  
**Severity:** MEDIUM  
**Short explanation:** The non-India phone number parsing logic is: `phone[:3] if phone[2].isdigit() and phone[3:4].isdigit() else phone[:3]` — both branches return `phone[:3]`, making the conditional dead code. Country codes with 2 digits (e.g., `+1` USA, `+7` Russia, `+44` UK) are incorrectly parsed as 3 characters, stripping the first digit of the phone number and creating a mismatched DB record.  
**Root cause:** Buggy ternary — both branches are identical.  
**User impact:** Non-Indian users cannot log in; phone lookup returns no match even for returning users.

---

### BUG-020
**Category:** Security — Sensitive Data Storage  
**File:** `app/modules/profile/models.py:152-155` (`Profile_Document`)  
**Severity:** MEDIUM  
**Short explanation:** Aadhaar card numbers, PAN card numbers, GST certificates, and trade licenses are stored in plaintext in `profile_documents.document_number (String(100))`. These are regulated personally identifiable / financial identifiers under Indian law (IT Act, PDPB).  
**Root cause:** No field-level encryption or tokenization applied to regulated document numbers.  
**User impact:** DB breach exposes government-issued identity documents; regulatory non-compliance.

---

### BUG-021
**Category:** Data Integrity  
**File:** `app/modules/post/service.py:334-344` (`record_share`)  
**Severity:** MEDIUM  
**Short explanation:** `record_share` has no idempotency protection. There is no `UniqueConstraint` on `PostShare(post_id, profile_id)` (confirmed in `post/models.py`). A user can spam the share endpoint and artificially inflate `share_count` without limit.  
**Root cause:** Unlike `PostLike` and `PostSave`, `PostShare` has no unique constraint.  
**User impact:** Fabricated share counts; distorted trending/recommendation signals.

---

### BUG-022
**Category:** Data Integrity  
**File:** `app/modules/post/service.py:313-327` (`delete_comment`)  
**Severity:** MEDIUM  
**Short explanation:** `delete_comment()` decrements `post.comment_count` unconditionally. If two concurrent requests delete the same comment (both pass the `comment.profile_id != profile_id` check before either commits), `comment_count` will be decremented twice but only one row is deleted. Count can go below the actual number of comments.  
**Root cause:** Non-atomic check-delete-decrement; no `MAX(0, count - 1)` guard.  
**User impact:** `comment_count` becomes negative or diverges from reality; shown to all users.

---

### BUG-023
**Category:** Security — No Rate Limiting  
**File:** `app/modules/auth/router.py:35-83` (`POST /auth/firebase-verify`)  
**Severity:** MEDIUM  
**Short explanation:** The Firebase verify endpoint has no rate limiting, IP throttling, or attempt counter. An attacker can enumerate valid phone numbers (by observing `is_new_user: true/false` response) or attempt token replay at any speed.  
**Root cause:** No middleware or per-route rate limiting configured at application or infrastructure level.  
**User impact:** Phone number enumeration; brute-force token replay attempts.

---

### BUG-024
**Category:** Logging Gap  
**File:** `app/modules/post/service.py:139-140`, `172-173`, `250-253`, `276-279`, `373-376`  
**Severity:** MEDIUM  
**Short explanation:** Five `except Exception: pass` blocks silently swallow all errors from the recommendation engine (index_post, remove_post_index, record_interaction). Failures are invisible — no log entry, no metric, no alerting.  
**Root cause:** Intentional design to not block user-facing operations, but logging was omitted.  
**User impact:** Recommendation engine can silently fail for hours/days with no way to diagnose it.

---

### BUG-025
**Category:** Performance / Memory  
**File:** `app/modules/news/tasks.py:213`  
**Severity:** MEDIUM  
**Short explanation:** `time.sleep(6)` is called synchronously inside the APScheduler background job to respect Gemini's rate limit. If there are 20 new articles from 10 RSS sources, the ingest job takes a minimum of 120 seconds blocking a thread. APScheduler uses a thread pool; a blocked thread reduces throughput for all scheduled jobs.  
**Root cause:** Synchronous sleep in a shared thread pool.  
**User impact:** Other background jobs (trending recalc, taste update) may queue-starve if ingest runs long; feeds stale during the block.

---

### BUG-026
**Category:** Configuration / Missing Feature  
**File:** `app/modules/news/tasks.py:411-436` (`push_breaking`)  
**Severity:** MEDIUM  
**Short explanation:** `push_breaking()` is implemented and identifies breaking news articles, but it is **never scheduled** in `main.py`. The function exists but never runs. Breaking news push notifications are completely silent.  
**Root cause:** Function defined but missing `scheduler.add_job(push_breaking, ...)` in the lifespan handler.  
**User impact:** Users never receive breaking news push notifications despite the feature being implemented.

---

### BUG-027
**Category:** Configuration / Crash  
**File:** `app/modules/profile/service.py:14-16`  
**Severity:** MEDIUM  
**Short explanation:** `_SUPABASE_URL = os.environ["DATABASE_STORAGE_URL"]` uses `os.environ[]` (raises `KeyError`) instead of `os.environ.get()`. If `DATABASE_STORAGE_URL` is absent from the environment, the **entire module fails to import**, crashing the entire application at startup before any routes are registered.  
**Root cause:** Hard `os.environ[]` subscription at module level, not at call time.  
**User impact:** Complete application startup failure if storage env vars are missing; not caught until deploy.

---

### BUG-028
**Category:** Reliability / Thread Safety  
**File:** `app/core/redis_client.py:13-25`  
**Severity:** MEDIUM  
**Short explanation:** Global `_client` is lazily initialized without a lock: two threads can simultaneously see `_client is None`, both create a `redis.Redis` instance, and the second assignment silently orphans the first connection pool. Under Gunicorn/uvicorn workers this results in leaked connections.  
**Root cause:** No `threading.Lock()` around the initialization check.  
**User impact:** Redis connection pool leaks; eventual `ConnectionError` under concurrent load.

---

### BUG-029
**Category:** Consistency — Response Format  
**File:** `app/modules/connections/service.py` (all service functions), `app/modules/connections/router.py`  
**Severity:** MEDIUM  
**Short explanation:** Connections and recommendations endpoints return raw dicts directly (e.g., `{"status": "following", ...}`, `{"user_id": ..., "total": ..., "followers": ...}`), while all other modules (profile, post, chat, feed, groups, news) wrap responses in `ok(data, message)`. The API has two incompatible response envelopes.  
**Root cause:** Connections module pre-dates the `ok()` wrapper convention and was never migrated.  
**User impact:** Frontend/mobile must handle two different response structures; increases integration bugs.

---

### BUG-030
**Category:** Data Integrity  
**File:** `app/modules/connections/service.py:168-181` (`send_message_request`)  
**Severity:** MEDIUM  
**Short explanation:** `MessageRequest` has `UniqueConstraint("sender_id", "receiver_id")` but no reverse-direction check. If A→B request exists (any status), B can still send B→A, creating a parallel open channel. Both users may accept each other simultaneously, creating two separate (but logically duplicate) request entries.  
**Root cause:** Business logic only checks `(sender_id, receiver_id)` direction, not both directions.  
**User impact:** Duplicate conversation requests; confusing UX; extra DB rows.

---

### BUG-031
**Category:** Validation  
**File:** `app/modules/post/schemas.py:56-78` (`PostCreate.validate_category_fields`)  
**Severity:** MEDIUM  
**Short explanation:** `category_id` and `commodity_id` are accepted as arbitrary integers with no validation that the IDs exist in the database. A post with `category_id=999` or `commodity_id=999` will be committed successfully and then fail silently in the recommendation indexer (which calls `CATEGORY_NAMES[category_id]` — a `KeyError`).  
**Root cause:** Validation happens only at the Pydantic layer (type check), not at the service layer (existence check).  
**User impact:** Corrupt posts in the database; recommendation indexing crash swallowed silently.

---

### BUG-032
**Category:** Security — No File Size Limit  
**File:** `app/modules/profile/service.py:492-526` (`update_avatar`)  
**Severity:** MEDIUM  
**Short explanation:** Avatar upload reads the entire file into memory (`content = await avatar.read()`) with no file size validation. An attacker can upload a multi-GB file, exhausting server memory or causing OOM on the container.  
**Root cause:** No `max_size` check before reading the upload.  
**User impact:** Denial of service via large file upload; potential OOM crash.

---

### BUG-033
**Category:** Data Integrity  
**File:** `app/modules/profile/service.py:399-410` (`delete_user`)  
**Severity:** LOW  
**Short explanation:** `delete_user()` sets `is_deleted=True`, `is_active=False` but does NOT clear `access_token` or `fcm_token`. A soft-deleted user's FCM token remains in the DB; push notifications may still be sent to their device. Their access token, if leaked, continues to pass DB lookups.  
**Root cause:** Incomplete cleanup on soft-delete path.  
**User impact:** Deleted users may still receive notifications; stale tokens pollute the users table.

---

### BUG-034
**Category:** Validation / Data Quality  
**File:** `app/modules/post/service.py:95-99` (`_profile_location`)  
**Severity:** LOW  
**Short explanation:** When a profile is not found, `_profile_location()` returns `(0.0, 0.0)` — coordinates for the Gulf of Guinea, off the coast of West Africa. Posts by users whose profile lookup fails will be indexed with a false location and appear in location-filtered feeds for Africa-region queries.  
**Root cause:** Silent fallback instead of raising an error.  
**User impact:** Location-based recommendation accuracy degraded for edge-case users.

---

### BUG-035
**Category:** Test Coverage Gap  
**File:** `backend/` (entire project)  
**Severity:** LOW  
**Short explanation:** There are zero unit tests or integration tests in the codebase. The `scripts/` and `testing/` directories contain manual e2e scripts but no `pytest` test suite, no CI configuration, and no assertions. All existing `test_*.py` files are ad-hoc HTTP scripts.  
**Root cause:** Tests were never written.  
**User impact:** Regressions are impossible to detect automatically; every deployment is a gamble.

---

### BUG-036
**Category:** Logging Gap  
**File:** `main.py:63`, `app/modules/news/tasks.py` (all tasks), `app/modules/post/post_recommendation_module/jobs.py`  
**Severity:** LOW  
**Short explanation:** Background scheduler jobs have no structured logging, no alerting on failure, and no observable success metrics. The only output is a bare `print()` statement in `ingest()`. Failed background jobs (trending recalc, taste update, post expiry) are silently retried after their interval with no record of the failure.  
**Root cause:** No logging framework configured at the application level.  
**User impact:** Background system failures are invisible; stale feeds, stale recommendations, accumulated broken state.

---

### BUG-037
**Category:** Validation  
**File:** `app/modules/post/router.py:26-34` (`GET /posts/`), `app/modules/post/router.py:37-45` (`GET /posts/mine`)  
**Severity:** LOW  
**Short explanation:** The `limit` parameter on all list endpoints (`get_feed`, `get_my_posts`, `get_following_feed`, `get_saved_posts`) has no upper bound. A caller can request `limit=1000000` and receive an unbounded DB result set, exhausting memory and DB connection time.  
**Root cause:** No `le=` constraint on the `Query` parameter.  
**User impact:** DoS via large limit values; server OOM; slow queries.

---

## Issue Map by Module

| Module | File | Bugs |
|--------|------|------|
| Auth | `auth/router.py`, `auth/service_msg91.py` | BUG-008, BUG-023 |
| Profile | `profile/router.py`, `profile/service.py`, `profile/models.py` | BUG-001, BUG-017, BUG-018, BUG-020, BUG-027, BUG-033 |
| Post | `post/router.py`, `post/service.py`, `post/models.py`, `post/schemas.py` | BUG-002, BUG-010, BUG-011, BUG-013, BUG-014, BUG-016, BUG-021, BUG-022, BUG-024, BUG-031, BUG-034, BUG-037 |
| Connections | `connections/router.py`, `connections/service.py`, `connections/models.py` | BUG-003, BUG-029, BUG-030 |
| Chat | `chat/presentation/router.py`, `chat/presentation/ws_router.py` | BUG-004 |
| Groups | `groups/router.py`, `groups/service.py` | BUG-005, BUG-015 |
| News | `news/tasks.py` | BUG-025, BUG-026 |
| Core | `core/security/jwt_handler.py`, `core/redis_client.py`, `core/config.py` | BUG-008, BUG-009, BUG-028 |
| Infrastructure | `.env`, global | BUG-006, BUG-007, BUG-019, BUG-035, BUG-036 |

---

## Priority Fix Order

### Immediate (before next deploy)
| Bug | Action |
|-----|--------|
| BUG-006 | Rotate all secrets in `.env`; add `.env` to `.gitignore`; use environment secrets manager |
| BUG-001 | Replace `Query(user_id)` with `Depends(get_current_user_id)` across all profile endpoints |
| BUG-002 | Add `current_user_id = Depends(get_current_user_id)` to all post endpoints; derive `profile_id` from it |
| BUG-003 | Add auth dependency to connections router; validate caller matches path `user_id` |
| BUG-004 | Add token validation to chat router and WebSocket handshake |
| BUG-005 | Add auth dependency to groups router |
| BUG-008 | Add `DEV_MODE`, `MSG91_AUTH_KEY`, `MSG91_TEMPLATE_ID` to `Settings` |

### Week 1
| Bug | Action |
|-----|--------|
| BUG-009 | Add `exp` claim to access tokens (7–30 day TTL) |
| BUG-013 | Replace `_active_profile_ids()` with a JOIN filter on `User.is_deleted == False` |
| BUG-014 | Batch `is_liked`/`is_saved` lookups per feed page, not per post |
| BUG-015 | Load group memberships in a single `IN` query, not per-group loop |
| BUG-012 | Merge two commits in `create_profile` into one atomic transaction |
| BUG-027 | Move `os.environ[]` to lazy accessor inside `update_avatar()` |

### Week 2
| Bug | Action |
|-----|--------|
| BUG-010, BUG-011 | Use atomic SQL `UPDATE … SET like_count = like_count + 1` inside the INSERT path with `ON CONFLICT` |
| BUG-016 | Fix `_active_profile_ids()` to join User and filter `is_deleted == False` |
| BUG-017 | Replace `if qmin and qmax` with `if qmin is not None and qmax is not None` |
| BUG-018 | Replace `assert` with proper `if not profile_resp: raise ProfileNotFoundError(...)` |
| BUG-019 | Rewrite E.164 country code splitter using a proper prefix table |
| BUG-020 | Encrypt document numbers at rest (AES-256 or Fernet) |
| BUG-021 | Add `UniqueConstraint("post_id", "profile_id")` to `PostShare` |
| BUG-022 | Add floor guard: `Post.comment_count = GREATEST(0, comment_count - 1)` |
| BUG-024 | Replace all `except Exception: pass` with `logger.exception(...)` |
| BUG-026 | Add `scheduler.add_job(push_breaking, "interval", minutes=5)` to lifespan |
| BUG-028 | Wrap Redis init with a `threading.Lock()` |
| BUG-032 | Add file size check (`len(content) > MAX_AVATAR_SIZE`) before upload |
| BUG-037 | Add `le=200` to all `limit` Query parameters |

### Backlog
| Bug | Action |
|-----|--------|
| BUG-007 | Encrypt access tokens at rest or remove storage entirely |
| BUG-023 | Add slowapi/rate-limiter middleware on auth endpoint |
| BUG-025 | Move Gemini calls to a queue/worker; use async sleep |
| BUG-029 | Migrate connections module to `ok()` response wrapper |
| BUG-030 | Add bidirectional uniqueness check in `send_message_request` |
| BUG-031 | Add DB existence check for `category_id` and `commodity_id` in post creation |
| BUG-033 | Clear `access_token` and `fcm_token` on `delete_user` |
| BUG-034 | Raise `PostForbiddenError` instead of returning `(0.0, 0.0)` in `_profile_location` |
| BUG-035 | Write `pytest` test suite with at least auth + profile + post happy-path coverage |
| BUG-036 | Configure structured logging (JSON) and scheduler job alerting |

---

*End of Phase 1 Audit — No code has been modified.*
