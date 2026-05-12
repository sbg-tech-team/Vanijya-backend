# Recommendation System — Developer Guide

A concise reference for anyone working on the vector-based matching engine.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Vector Architecture](#2-vector-architecture)
3. [Encoding Details](#3-encoding-details)
4. [IS vs WANT Vectors](#4-is-vs-want-vectors)
5. [Boost Weights](#5-boost-weights)
6. [Database Layer](#6-database-layer)
7. [API Endpoints](#7-api-endpoints)
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
                                                     top-20 ranked matches
```

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

One-hot encoding against `ALL_COMMODITIES` in `app/config.py`.

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

Affinity and offers tables live in `app/config.py` under `ROLE_AFFINITY` and `ROLE_OFFERS`.

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

All weights live in `app/config.py`. Changing any of them **invalidates all stored embeddings** — run `python migrate_pgvec.py --reset` afterwards.

| Constant | Value | Effect |
|---|---|---|
| `GEO_BOOST` | 3.0 | Strongest signal — prioritises nearby users |
| `ROLE_BOOST` | 1.5 | Mid-weight — role compatibility |
| `COMMODITY_BOOST` | 0.9 | Slightly subdued — commodity overlap |
| `QTY_BOOST` | 1.0 | Tune to increase/decrease quantity scale importance |
| `QTY_REF_MAX` | 1 000 000 | Reference ceiling for log normalisation (MT) |

**Tuning rule of thumb:** The effective influence of a component is roughly `boost × average_component_magnitude`. Geo wins at 3.0 × 1.0 (unit sphere). To make quantity more influential, raise `QTY_BOOST` toward 2.0–3.0.

---

## 6. Database Layer

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

```sql
SELECT user_id,
       1 - (is_vector <=> CAST(:vec AS vector)) AS similarity
FROM user_embeddings
WHERE user_id != :uid
  AND is_vector IS NOT NULL
ORDER BY is_vector <=> CAST(:vec AS vector)   -- HNSW walks the graph
LIMIT 20
```

`<=>` is pgvector's cosine distance operator. `1 - distance = similarity`. Results are returned best-first. The HNSW index makes this O(log N) regardless of how many users are in the table.

---

## 7. API Endpoints

All recommendation endpoints live under the connections router (`/recommendations`).

### `GET /recommendations/`

Fetch top 20 matches for the authenticated user. Requires `Authorization: Bearer <token>`.

1. Loads the user's profile (role + commodities) from DB.
2. Builds their WANT vector using `build_query_vector()`.
3. Runs HNSW ANN cosine search via pgvector `<=>`, excluding the user themselves.
4. **Filters out users the requesting user is already following** — results only contain users not yet connected.
5. Returns top 20 with full profile info and similarity score.

**Response:**
```json
{
  "user_id": "c37a3257-dc3f-43be-9fb0-33cf918b11ff",
  "role": "trader",
  "commodity": ["rice", "cotton"],
  "qty_range": "100–500mt",
  "total": 20,
  "results": [
    {
      "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "name": "Ravi Kumar",
      "role": "exporter",
      "commodity": ["rice"],
      "is_verified": true,
      "qty_range": "200–800mt",
      "similarity": 0.9312
    }
  ]
}
```

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

**Response:** same `results` format as above (no `user_id` in the outer wrapper).

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

**After changing encoding logic or boost weights**, IS vectors in the DB are stale. Rebuild them by re-saving every profile (which triggers `_upsert_user_embedding`). For a bulk rebuild in development:

```sql
-- Force all embeddings to rebuild on next profile update
UPDATE user_embeddings SET is_vector = NULL;
```

Then call `GET /recommendations/{user_id}/refresh` equivalent or re-run the profile update endpoint for each user.

---

## 9. Extending the System

### Adding a new commodity

1. Append to `ALL_COMMODITIES` in `app/config.py` — **only at the end, never in the middle**.
2. The vector dimension increases by 1 — update the Supabase column: `ALTER TABLE "Users" ALTER COLUMN embedding TYPE vector(N)`.
3. Re-run `python migrate_pgvec.py --reset` to rebuild all embeddings.

### Adding a new role

1. Add the role to `ROLE_AFFINITY` and `ROLE_OFFERS` in `app/config.py`.
2. If you're adding a new *dimension* (e.g. a fourth role type), `ROLE_DIMS` grows, the vector dimension increases, and you need to follow the same column + reset steps as above.
3. If the new role fits within existing dimensions (just new affinity/offers weights), no dimension change is needed — just re-run `--reset`.

### Changing boost weights

Edit the constants in `app/config.py`, then run `python migrate_pgvec.py --reset`. No schema changes needed.

---

## 10. Tuning Guide

| Goal | What to change |
|---|---|
| Prioritise geographic proximity more | Increase `GEO_BOOST` |
| Make role compatibility matter more | Increase `ROLE_BOOST` |
| Make quantity scale-matching matter more | Increase `QTY_BOOST` toward 2.0–3.0 |
| Adjust how role types seek each other | Edit `ROLE_AFFINITY` in `config.py` |
| Change what each role signals it offers | Edit `ROLE_OFFERS` in `config.py` |

**After any config change:** `python migrate_pgvec.py --reset`

**Testing a change without a full reset:** call `GET /recommendations/{user_id}/refresh` on a handful of representative users and compare similarity scores before and after.
