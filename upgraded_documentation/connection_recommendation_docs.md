# Recommendation System — Developer Guide

A concise reference for anyone working on the vector-based matching engine.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Vector Architecture](#2-vector-architecture)
3. [Encoding Details](#3-encoding-details)
4. [IS vs WANT Vectors](#4-is-vs-want-vectors)
5. [Boost Weights](#5-boost-weights)
6. [Database & Cache Layer](#6-database--cache-layer)
7. [API Endpoints](#7-api-endpoints) — GET · POST seen · DELETE seen · POST search
8. [Migration Script](#8-migration-script)
9. [Extending the System](#9-extending-the-system)
10. [Tuning Guide](#10-tuning-guide)

---

## 1. System Overview

Users are matched by encoding their profile into a fixed-size floating-point vector and running a cosine similarity search against all stored vectors using the **pgvector HNSW index** on Supabase (Postgres).

```
User profile  ──encode──►  vector(11)  ──stored in──►  user_embeddings.is_vector
                                                              │
Search request ──encode──►  WANT vector  ──HNSW ANN (<=>)───►│
                                                              ▼
                                                     top-N ranked matches
                                                              │
                                              filter: already-following
                                              filter: already-requested
                                              filter: seen set (Redis, 48h TTL)
                                                              ▼
                                                     final paginated results
```

**Exclusion layers** (applied on every `GET /recommendations/`):

| Layer | Source | Persistence |
|---|---|---|
| Already following | `user_connections` table | Permanent |
| Already sent message request | `message_requests` table | Until withdrawn/resolved |
| Seen cards | Redis Set per user | 48 hours from first seen, then resets |

Every user has **two logical vectors**:

| Name | Purpose | Stored? |
|---|---|---|
| **IS vector** (candidate) | What the user *is* — their profile | ✅ Yes, in `user_embeddings.is_vector` |
| **WANT vector** (query) | What the user *wants* — built at query time | ❌ Never stored |

---

## 2. Vector Architecture

The embedding is `vector(11)` — 11 floats in a fixed layout. **Never reorder or remove dimensions** — doing so invalidates every stored embedding.

```
Index  Dims  Component     Notes
─────  ────  ───────────   ──────────────────────────────────────
0–2      3   Commodity     One-hot, boosted by COMMODITY_BOOST
3–5      3   Role          Soft scores, boosted by ROLE_BOOST
6–8      3   Geo           3D Cartesian (unit sphere), boosted by GEO_BOOST
9–10     2   Quantity      log1p-normalised, boosted by QTY_BOOST
─────  ────
Total   11
```

To verify the dimension count at runtime:

```python
from app.encoding.vector import vector_dim   # returns 11
from app.encoding.vector import vector_layout  # returns a labelled breakdown
```

---

## 3. Encoding Details

### 3.1 Commodity (`dims 0–2`)

One-hot encoding against `ALL_COMMODITIES` in `app/modules/connections/weights_config.py`.

```python
# Example: user trades cotton and rice
encode_commodity(["cotton", "rice"])
# → [0.9, 0.9, 0.0]   (COMMODITY_BOOST = 0.9 applied)
```

- Unknown commodities are **silently ignored**.
- To add a commodity, append it to `ALL_COMMODITIES` — **never insert in the middle**.

### 3.2 Role (`dims 3–5`)

Soft-score encoding. Two variants exist:

| Variant | Function | Used in |
|---|---|---|
| IS (`ROLE_OFFERS`) | What this role *provides* | Candidate / stored vector |
| WANT (`ROLE_AFFINITY`) | What this role *looks for* | Query / search vector |

```python
# IS example: a trader
encode_role_candidate("trader")   # → [0.0, 0.0, 1.5]  (broker, exporter, trader)

# WANT example: a trader looking for partners
encode_role_searcher("trader")    # → [0.825, 0.45, 0.30]
```

Affinity and offers tables live in `app/modules/connections/weights_config.py` under `ROLE_AFFINITY` and `ROLE_OFFERS`.

### 3.3 Geo (`dims 6–8`)

Lat/lon is projected onto a **3D unit sphere** (Cartesian coordinates). Cosine similarity on unit-sphere vectors is equivalent to great-circle proximity.

```python
encode_geo(lat, lon)
# → [cos(lat)cos(lon),  cos(lat)sin(lon),  sin(lat)]
# multiplied by GEO_BOOST (3.0) during assembly
```

`GEO_BOOST = 3.0` is the strongest signal by design — location is the primary matching factor.

### 3.4 Quantity (`dims 9–10`)

**Why log-normalise?** Raw values like `50 000 MT` have a vector magnitude ~50 000. The geo component has magnitude ~3.0. Raw quantity would completely dominate cosine similarity, overriding every other boost.

Log normalisation compresses the range and keeps quantity in the same ballpark as the other components:

```python
log_ref = log1p(QTY_REF_MAX)          # log1p(1_000_000) ≈ 13.8
encoded = log1p([qty_min, qty_max]) / log_ref * QTY_BOOST
```

Approximate output values:

| Quantity (MT) | Encoded value (`QTY_BOOST=1.0`) |
|---|---|
| 0 | 0.00 |
| 100 | 0.33 |
| 500 | 0.45 |
| 5 000 | 0.61 |
| 50 000 | 0.78 |
| 1 000 000 | 1.00 |

Small traders (`[100, 500]`) and large traders (`[5 000, 50 000]`) now point in meaningfully different directions — cosine similarity will distinguish them.

---

## 4. IS vs WANT Vectors

This is the core design decision. Users stored in the DB have an IS vector (what they offer). When searching, a WANT vector is built from the same user (what they're looking for).

```
build_candidate_vector(...)   →  IS vector   →  stored in "Users".embedding
build_query_vector(...)       →  WANT vector →  used as ANN query, never stored
```

The role encoding differs between them (`ROLE_OFFERS` vs `ROLE_AFFINITY`). Commodity, geo, and quantity use the same encoding in both.

```python
# Both functions share the same signature:
build_candidate_vector(commodity_list, role, lat, lon, qty_min, qty_max)
build_query_vector(commodity_list, role, lat, lon, qty_min, qty_max)
```

---

## 5. Boost Weights

All weights live in `app/modules/connections/weights_config.py`. Changing any of them **invalidates all stored embeddings** — null out stored vectors (`UPDATE user_embeddings SET is_vector = NULL`) and trigger a profile update for each user.

| Constant | Value | Effect |
|---|---|---|
| `GEO_BOOST` | 3.0 | Strongest signal — prioritises nearby users |
| `ROLE_BOOST` | 1.5 | Mid-weight — role compatibility |
| `COMMODITY_BOOST` | 0.9 | Slightly subdued — commodity overlap |
| `QTY_BOOST` | 1.0 | Tune to increase/decrease quantity scale importance |
| `QTY_REF_MAX` | 1 000 000 | Reference ceiling for log normalisation (MT) |

**Tuning rule of thumb:** The effective influence of a component is roughly `boost × average_component_magnitude`. Geo wins at 3.0 × 1.0 (unit sphere). To make quantity more influential, raise `QTY_BOOST` toward 2.0–3.0.

---

## 6. Database & Cache Layer

### Schema

```sql
-- user_embeddings table (created by alembic migration b5e7f9a2c3d1)
-- Column type migrated JSONB → VECTOR(11) by migration a3b4c5d6e7f8

CREATE TABLE user_embeddings (
    user_id   UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    is_vector VECTOR(11),          -- 11-dim IS vector, nullable until first profile save
    updated_at TIMESTAMP NOT NULL
);

-- HNSW index for cosine ANN search (migration a3b4c5d6e7f8)
CREATE INDEX ix_user_embeddings_hnsw
    ON user_embeddings USING hnsw (is_vector vector_cosine_ops);
```

Schema setup is handled entirely by **Alembic migrations** — no manual SQL or separate scripts needed. Run `alembic upgrade head` once on a fresh database.

### Key files

| File | Responsibility |
|---|---|
| `app/modules/profile/models.py` | `UserEmbedding` ORM model (`Vector(11)` column) |
| `app/modules/profile/service.py` | `_upsert_user_embedding()` — builds and stores IS vector on profile create/update |
| `app/modules/connections/service.py` | `get_recommendations()`, `custom_recommendation_search()` — HNSW ANN query |
| `app/modules/connections/encoding/vector.py` | `build_candidate_vector()`, `build_query_vector()` |

### Live ANN query (`connections/service.py`)

Before hitting Postgres, the service fetches the user's seen set from Redis:

```python
seen_ids = redis.smembers(f"rec:seen:{user_id}")   # set of UUID strings
# passed to SQL as: string_to_array(:seen_csv, ',')::uuid[]
```

If Redis is unreachable the seen filter is skipped gracefully — recommendations still work, just without seen filtering.

```sql
-- Count query (runs first — determines total_available)
SELECT COUNT(*) AS cnt
FROM user_embeddings
WHERE user_id != :uid
  AND is_vector IS NOT NULL
  AND user_id NOT IN (
      SELECT following_id FROM user_connections WHERE follower_id = :uid
  )
  AND user_id NOT IN (
      SELECT receiver_id FROM message_requests WHERE sender_id = :uid
  )
  AND user_id != ALL(string_to_array(:seen_csv, ',')::uuid[]);  -- omitted when seen set is empty

-- Page query
SELECT user_id,
       1 - (is_vector <=> CAST(:vec AS vector)) AS similarity
FROM user_embeddings
WHERE user_id != :uid
  AND is_vector IS NOT NULL
  AND user_id NOT IN (
      SELECT following_id FROM user_connections WHERE follower_id = :uid
  )
  AND user_id NOT IN (
      SELECT receiver_id FROM message_requests WHERE sender_id = :uid
  )
  AND user_id != ALL(string_to_array(:seen_csv, ',')::uuid[])   -- omitted when seen set is empty
ORDER BY is_vector <=> CAST(:vec AS vector)   -- HNSW walks the graph
LIMIT :lim OFFSET :off
```

`<=>` is pgvector's cosine distance operator. `1 - distance = similarity`. Results are returned best-first. The HNSW index makes this O(log N). `OFFSET` shifts the window per page — page 1 = offset 0, page 2 = offset 20, etc.

### Redis seen set

```
Key:    rec:seen:{user_id}
Type:   Redis Set
Values: UUID strings of users the client has shown as recommendation cards
TTL:    172 800 s (48 hours) — set ONCE when the key is first created, never reset on updates
```

The TTL starts at first write and counts down regardless of further activity. After 48 hours Redis auto-deletes the key and the user's seen set resets — those people will reappear in recommendations. **No Alembic migration and no scheduled cleanup job are needed.**

---

## 7. API Endpoints

All recommendation endpoints live under the connections router (`/recommendations`).

### `GET /recommendations/`

Fetch paginated matches for the authenticated user. Requires `Authorization: Bearer <token>`.

1. Loads the user's profile (role + commodities + location + quantity) from Postgres.
2. Builds their WANT vector using `build_query_vector()`.
3. Fetches the user's seen set from Redis (`rec:seen:{user_id}`).
4. Runs HNSW ANN cosine search via pgvector `<=>` with three exclusion filters:
   - Users the caller is already **following**
   - Users the caller has already **sent a message request to**
   - Users in the caller's **seen set** (Redis, 48-hour window)
5. Returns one page of results with full profile info and similarity score.

| Query Param | Required | Type | Default | Description |
|---|---|---|---|---|
| `page` | No | int | `1` | Page number (1-based) |
| `limit` | No | int | `20` | Results per page (max 100) |

**Response:**
```json
{
  "user_id": "c37a3257-dc3f-43be-9fb0-33cf918b11ff",
  "role": "trader",
  "commodity": ["rice", "cotton"],
  "qty_range": "100–500mt",
  "page": 1,
  "limit": 20,
  "total_available": 85,
  "has_more": true,
  "total": 20,
  "results": [
    {
      "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "name": "Ravi Kumar",
      "avatar_url": null,
      "role": "exporter",
      "commodity": ["rice"],
      "is_user_verified": true,
      "is_business_verified": false,
      "quantity_min": 200,
      "quantity_max": 800,
      "business_name": "Ravi Agro Pvt Ltd",
      "city": "Mumbai",
      "state": "Maharashtra",
      "similarity": 0.9312
    }
  ]
}
```

- `total_available` — total candidates remaining after all exclusions (following + requested + seen). **When this is `0`, the user has seen everyone in the pool — show the empty state screen.**
- `has_more` — `false` when the last page is reached. Stop infinite scroll when this is `false`.
- `total` — count of items in this specific page response.

**Empty state / pool exhaustion:**

When `total_available == 0` the frontend should show an empty state and offer a reset:

```
total_available == 0
       ↓
Show: "You've seen everyone! Tap to start over."
       ↓  [Start Over] button
DELETE /recommendations/seen        ← clears seen set
       ↓
GET /recommendations/?page=1        ← fresh results
```

Use `total_available == 0` as the trigger, not `results` being empty — a high page number can return an empty `results` array while `total_available` is still > 0.

---

### `POST /recommendations/seen`

Mark recommendation cards as seen. Excluded from future `GET /recommendations/` responses for 48 hours. Requires `Authorization: Bearer <token>`.

**Request body:**
```json
{
  "user_ids": ["uuid1", "uuid2", "uuid3"]
}
```

| Field | Required | Type | Constraint |
|---|---|---|---|
| `user_ids` | Yes | list of UUID | Max 50 per call |

**Response:** `204 No Content` — no body.

**When to call (frontend):**
- When 10 seen IDs accumulate in the local buffer
- When the app goes to background (`AppLifecycleState.paused`)

**Behaviour:**
- Best-effort — no retry on failure, backend silently ignores Redis errors.
- The seen set TTL (48 h) is set **once at first write** and never reset by subsequent calls. After 48 hours the set auto-expires in Redis and those users reappear in recommendations.
- No Postgres writes — stored entirely in Redis.

---

### `DELETE /recommendations/seen`

Clear the calling user's entire seen set. All previously seen users resurface immediately in the next `GET /recommendations/` call. Requires `Authorization: Bearer <token>`.

**Request body:** none.

**Response:** `204 No Content` — no body.

**When to call (frontend):**
- User taps "Start Over" / "Reset" on the empty-state screen (when `total_available == 0`).

**Behaviour:**
- Deletes the Redis key `rec:seen:{user_id}` instantly.
- The next `GET /recommendations/` returns the full pool sorted by relevance as if the user is new.
- Best-effort — if Redis is unavailable the key may not be deleted, but the endpoint still returns 204.

---

### `POST /recommendations/search`

Ad-hoc search without needing an existing `user_id`. Useful for previewing matches before or during signup.

**Request body:**
```json
{
  "commodity": ["rice", "cotton"],
  "role": "trader",
  "latitude_raw": 19.076,
  "longitude_raw": 72.877,
  "qty_min_mt": 100,
  "qty_max_mt": 500
}
```

No auth required.

**Response:** same `results` array format as above (no `user_id`, `page`, or `has_more` in the outer wrapper — just `total` and `results`).

---

## 8. Migration

Schema setup is fully managed by **Alembic**. No separate scripts are needed.

```bash
# Apply all migrations (including pgvector setup and HNSW indexes):
alembic upgrade head

# Roll back the pgvector migration if needed:
alembic downgrade f6a7b8c9d0e1
```

**What the migrations do:**

| Revision | What it creates |
|---|---|
| `b5e7f9a2c3d1` | `user_embeddings` table with `is_vector JSONB` |
| `a3b4c5d6e7f8` | Converts `is_vector` to `VECTOR(11)`, creates HNSW index |

**After changing encoding logic or boost weights**, IS vectors in the DB are stale. Rebuild them by re-saving every profile (which triggers `_upsert_user_embedding` in `app/modules/profile/service.py`). For a bulk rebuild in development:

```sql
-- Null out all stored embeddings
UPDATE user_embeddings SET is_vector = NULL;
```

Then call `PATCH /profile/` (with any field) for each user to trigger `_upsert_user_embedding` and rebuild their vector.

---

## 9. Extending the System

### Adding a new commodity

1. Append to `ALL_COMMODITIES` in `app/modules/connections/weights_config.py` — **only at the end, never in the middle**.
2. The vector dimension increases by 1 — update the Supabase column: `ALTER TABLE "Users" ALTER COLUMN embedding TYPE vector(N)`.
3. Re-run `python migrate_pgvec.py --reset` to rebuild all embeddings.

### Adding a new role

1. Add the role to `ROLE_AFFINITY` and `ROLE_OFFERS` in `app/modules/connections/weights_config.py`.
2. If you're adding a new *dimension* (e.g. a fourth role type), `ROLE_DIMS` grows, the vector dimension increases, and you need to follow the same column + reset steps as above.
3. If the new role fits within existing dimensions (just new affinity/offers weights), no dimension change is needed — just re-run `--reset`.

### Changing boost weights

Edit the constants in `app/modules/connections/weights_config.py`, then null out stored vectors and trigger profile updates to rebuild embeddings. No schema changes needed.

---

## 10. Tuning Guide

| Goal | What to change |
|---|---|
| Prioritise geographic proximity more | Increase `GEO_BOOST` |
| Make role compatibility matter more | Increase `ROLE_BOOST` |
| Make quantity scale-matching matter more | Increase `QTY_BOOST` toward 2.0–3.0 |
| Adjust how role types seek each other | Edit `ROLE_AFFINITY` in `config.py` |
| Change what each role signals it offers | Edit `ROLE_OFFERS` in `config.py` |

**After any config change:** null out `user_embeddings.is_vector` and trigger profile updates to rebuild all embeddings.

**Testing a change without a full reset:** call `GET /recommendations/` for a handful of representative users and compare similarity scores before and after.
