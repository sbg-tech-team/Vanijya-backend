# Authentication & Access Control

> **Updated:** 2026-05-12  
> Covers the fixes applied to resolve OWASP A01 (Broken Access Control) across all API routers.

---

## Overview

Every protected endpoint derives the acting user's identity from the **signed JWT Bearer token** — never from a client-supplied query parameter, path parameter, or request body field.

Before this fix, routes like `GET /feed/home?user_id=<uuid>` allowed any client to impersonate any user by swapping the UUID. That is now impossible.

---

## How Authentication Works

```
Client                          FastAPI
  │                                │
  │  GET /feed/home                │
  │  Authorization: Bearer <jwt>   │
  │ ──────────────────────────────►│
  │                                │  OAuth2PasswordBearer extracts token
  │                                │  decode_access_token(token)
  │                                │  → claims.user_id  (UUID)
  │                                │  → claims.profile_id (int)
  │                                │
  │  200 OK { success, message, data }
  │ ◄──────────────────────────────│
```

### Token acquisition

Tokens are issued at login:

```
POST /auth/token
→ { access_token, refresh_token, token_type: "bearer", expires_in }
```

All subsequent requests must include:

```
Authorization: Bearer <access_token>
```

---

## Identity Dependencies

Three dependency functions in [app/dependencies.py](../app/dependencies.py) centralise identity extraction:

| Dependency | Returns | Used by |
|------------|---------|---------|
| `get_current_user` | `CurrentUser(user_id: UUID, profile_id: int)` | Profile router |
| `get_current_user_id` | `UUID` | Feed, News, Groups, Connections routers |
| `get_current_profile_id` | `int` | Posts router |

All three decode the same JWT — they are convenience wrappers, not separate auth mechanisms.

```python
# Example — correct usage in a route
@router.get("/my/feed")
def my_feed(
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return ok(get_feed(db, user_id))
```

**Never do this:**
```python
# WRONG — client can pass any UUID
user_id: UUID = Query(..., description="Acting user's UUID")
```

---

## Response Envelope

Every endpoint returns the `ok()` envelope from [app/shared/utils/response.py](../app/shared/utils/response.py):

```json
{
  "success": true,
  "message": "Human-readable status",
  "data": { ... }
}
```

---

## HTTP Status Codes

| Code | When |
|------|------|
| `200` | Successful GET / PATCH |
| `201` | Successful POST (resource created) |
| `204` | Successful DELETE (no body) |
| `400` | Validation error (bad input) |
| `401` | Missing or invalid Bearer token |
| `403` | Authenticated but not authorised (e.g. not group admin) |
| `404` | Resource not found |
| `409` | Conflict (duplicate follow, duplicate request, etc.) |
| `422` | Request body / query param schema violation |

---

## Protected Endpoints by Router

### Feed (`/feed`)

| Method | Path | Auth |
|--------|------|------|
| GET | `/feed/home` | `get_current_user_id` |
| POST | `/feed/engagement` | `get_current_user_id` |

### News (`/news`)

| Method | Path | Auth |
|--------|------|------|
| GET | `/news/feed` | `get_current_user_id` |
| GET | `/news/my/taste` | `get_current_user_id` |
| GET | `/news/my/history` | `get_current_user_id` |
| GET | `/news/saved` | `get_current_user_id` |
| GET | `/news/{article_id}` | `get_current_user_id` |
| POST | `/news/{article_id}/engage` | `get_current_user_id` |
| POST | `/news/{article_id}/like` | `get_current_user_id` |
| POST | `/news/{article_id}/save` | `get_current_user_id` |
| POST | `/news/{article_id}/share` | `get_current_user_id` |
| POST | `/news/{article_id}/comment` | `get_current_user_id` |

### Groups (`/api/v1/groups`)

| Method | Path | Auth |
|--------|------|------|
| GET | `/api/v1/groups/` | `get_current_user_id` |
| POST | `/api/v1/groups/` | `get_current_user_id` |
| GET | `/api/v1/groups/suggestions` | `get_current_user_id` |
| GET | `/api/v1/groups/{group_id}` | `get_current_user_id` |
| PATCH | `/api/v1/groups/{group_id}` | `get_current_user_id` |
| PATCH | `/api/v1/groups/{group_id}/permissions` | `get_current_user_id` |
| POST | `/api/v1/groups/{group_id}/join` | `get_current_user_id` |
| DELETE | `/api/v1/groups/{group_id}/leave` | `get_current_user_id` |
| GET | `/api/v1/groups/{group_id}/members` | `get_current_user_id` |
| POST | `/api/v1/groups/{group_id}/members/add` | `get_current_user_id` |
| DELETE | `/api/v1/groups/{group_id}/members/{target_user_id}` | `get_current_user_id` |
| POST | `/api/v1/groups/{group_id}/members/{target_user_id}/freeze` | `get_current_user_id` |
| DELETE | `/api/v1/groups/{group_id}/members/{target_user_id}/freeze` | `get_current_user_id` |
| POST | `/api/v1/groups/{group_id}/mute` | `get_current_user_id` |
| POST | `/api/v1/groups/{group_id}/favorite` | `get_current_user_id` |
| GET | `/api/v1/groups/{group_id}/invite-link` | `get_current_user_id` |
| POST | `/api/v1/groups/{group_id}/report` | `get_current_user_id` |

### Posts (`/posts`)

| Method | Path | Auth |
|--------|------|------|
| POST | `/posts/upload-image` | `get_current_profile_id` |
| POST | `/posts/` | `get_current_profile_id` |
| GET | `/posts/` | `get_current_profile_id` |
| GET | `/posts/mine` | `get_current_profile_id` |
| GET | `/posts/following` | `get_current_profile_id` |
| GET | `/posts/saved` | `get_current_profile_id` |
| GET | `/posts/{post_id}` | `get_current_profile_id` |
| PATCH | `/posts/{post_id}` | `get_current_profile_id` |
| DELETE | `/posts/{post_id}` | `get_current_profile_id` |
| POST | `/posts/{post_id}/like` | `get_current_profile_id` |
| GET | `/posts/{post_id}/comments` | `get_current_profile_id` |
| POST | `/posts/{post_id}/comments` | `get_current_profile_id` |
| DELETE | `/posts/{post_id}/comments/{comment_id}` | `get_current_profile_id` |
| POST | `/posts/{post_id}/share` | `get_current_profile_id` |
| POST | `/posts/{post_id}/save` | `get_current_profile_id` |

### Connections (`/connections`)

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| POST | `/connections/follow/{target_id}` | `get_current_user_id` | |
| DELETE | `/connections/follow/{target_id}` | `get_current_user_id` | |
| GET | `/connections/follow/status/{target_id}` | `get_current_user_id` | |
| GET | `/connections/{user_id}/followers` | Public | View any user's followers |
| GET | `/connections/{user_id}/following` | Public | View any user's following |
| POST | `/connections/message-request/{target_id}` | `get_current_user_id` | |
| DELETE | `/connections/message-request/{target_id}` | `get_current_user_id` | |
| PATCH | `/connections/message-request/{request_id}/accept` | `get_current_user_id` | |
| PATCH | `/connections/message-request/{request_id}/decline` | `get_current_user_id` | |
| GET | `/connections/message-requests/received` | `get_current_user_id` | |
| GET | `/connections/message-requests/sent` | `get_current_user_id` | |
| GET | `/connections/search` | `get_current_user_id` | |
| GET | `/connections/search/suggestions` | Public | No auth needed |

### Recommendations (`/recommendations`)

| Method | Path | Auth |
|--------|------|------|
| GET | `/recommendations/` | `get_current_user_id` |
| POST | `/recommendations/search` | Public |

---

## What Changed (2026-05-12)

### Before
- Identity passed as `?user_id=<uuid>` query param or `/{user_id}/` path param
- Any client could impersonate any user
- Connections router had no auth: *"No auth token required"*
- Response shapes inconsistent across routers

### After
- Identity derived exclusively from `Depends(get_current_user_id)` or `Depends(get_current_profile_id)`
- All mutation endpoints require a valid Bearer token — 401 otherwise
- Connections routes restructured: `/{user_id}/follow/{target_id}` → `/follow/{target_id}`
- All responses use `ok()` envelope
- Status codes standardised: 201 creates, 204 deletes, 409 conflicts

### Files changed

| File | Change |
|------|--------|
| `app/dependencies.py` | Added `get_current_profile_id` |
| `app/modules/feed/router.py` | `Query(user_id)` → `Depends(get_current_user_id)` |
| `app/modules/news/router.py` | `Query(user_id)` → `Depends(get_current_user_id)` |
| `app/modules/groups/router.py` | `Query(user_id)` → `Depends(get_current_user_id)`; `/suggestions/{user_id}` → `/suggestions` |
| `app/modules/post/router.py` | `Query(profile_id)` → `Depends(get_current_profile_id)` |
| `app/modules/connections/router.py` | Full rewrite — path-param identity removed, Bearer token required, `ok()` added |
| `app/modules/profile/router.py` | Added `status_code=201` to `POST /` and `POST /verify` |

---

## Testing

```bash
# Run the full access-control test suite (62 tests, no live DB needed)
pytest tests/test_security_fixes.py -v

# What it covers:
#   34 tests — 401 without token across all routers
#    7 tests — identity comes from token, not query param
#    7 tests — ok() envelope on every response
#   13 tests — 201/204/409 status codes + old routes return 404
```
