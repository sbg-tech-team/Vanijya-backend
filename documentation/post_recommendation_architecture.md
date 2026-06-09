# Post Recommendation System — Technical Architecture Document

> Codebase snapshot: 2026-06-08  
> Scope: Post recommendation, post interaction tracking, user taste profiles.  
> All constants, formulas, and behaviors are traced directly from source code.

---

## File Inventory

```
app/modules/post/
├── models.py                                    Post, PostView, PostLike, PostComment, PostShare, PostSave, PostDealDetails
├── router.py                                    Post CRUD + interaction endpoints
├── service.py                                   Post CRUD, view recording, interaction triggers
│
├── post_recommendation_module/
│   ├── constants.py                             All recommendation constants
│   ├── models.py                                PostEmbedding, PopularPost, SeenPost
│   ├── router.py                                Feed + job trigger endpoints
│   ├── schemas.py                               FeedPostCard, FeedResponse, JobResult
│   ├── service.py                               Recommendation pipeline (index, retrieve, rerank)
│   ├── jobs.py                                  run_expiry_job(), run_popular_posts_sync()
│   └── vector.py                                build_post_vector(), build_user_feed_vector(), weighted_cosine_similarity()
│
└── post_user_interaction/
    ├── constants.py                             Signal weights, dwell thresholds, taste constants
    ├── models.py                                PostInteractionEvent, UserPostTaste, UserTasteProfile
    ├── router.py                                Batch endpoint + job trigger endpoints
    ├── schemas.py                               InteractionBatchPayload, InteractionBatchResult
    ├── service.py                               process_interaction_batch(), record_interaction(), get_taste_for_feed()
    ├── taste_service.py                         update_taste(), get_taste_weights(), get_author_affinity()
    └── jobs.py                                  run_taste_update_job(), run_ignore_detection_job()

app/modules/profile/
└── models.py                                    Profile, Business, UserEmbedding (post_feed_vector)

app/core/
└── scheduler.py                                 APScheduler — 4 post-related jobs

main.py                                          Router registration
```

---

## Part 1 — System Overview

### What the system does

The post recommendation system delivers a personalised ranked list of posts to each user's home feed. It learns from every user interaction — scroll dwell time, opens, likes, saves, comments, shares — and continuously refines a multi-dimensional taste profile for each user. That taste profile, combined with vector similarity, post freshness, post engagement quality, and social graph signals, produces a ranked candidate list. A diversity filter then enforces variety before the final feed is returned.

### What data it uses

| Data source | Purpose |
|-------------|---------|
| `post_embeddings` | 10-dim pgvector representing each post's commodity, target role, geo, and quantity |
| `user_embeddings.post_feed_vector` | Pre-built 10-dim user vector; falls back to `build_user_feed_vector()` if absent |
| `user_post_taste` | Row-per-dimension float taste scores: category, commodity, author affinity |
| `user_taste_profiles` | Legacy integer category counters (still written; no longer read by reranker) |
| `post_interaction_events` | Append-only log of every behavioural signal |
| `seen_posts` | Per-user set of posts excluded from feed for 30 days |
| `popular_posts` | Pre-computed velocity-scored pool refreshed every 15 minutes |
| `profile`, `business` | User role, commodity preferences, geo coordinates |
| `user_connections` | Followed user IDs for the 1.5× social boost |
| `posts` | Engagement counters (like_count, comment_count, save_count), created_at for freshness |

### Tables that participate

`posts`, `post_embeddings`, `popular_posts`, `seen_posts`, `post_views`, `post_likes`, `post_saves`, `post_comments`, `post_shares`, `post_interaction_events`, `user_post_taste`, `user_taste_profiles`, `user_embeddings`, `profile`, `business`, `profile_commodities`, `user_connections`

### Services that participate

| Service module | Role |
|----------------|------|
| `post_recommendation_module/service.py` | Feed pipeline: vector retrieval, reranking, card construction |
| `post_user_interaction/service.py` | Batch event ingestion, synchronous taste updates |
| `post_user_interaction/taste_service.py` | Atomic taste upserts, decayed weight reads |
| `post_user_interaction/jobs.py` | Async dwell processing, ignore detection |
| `post_recommendation_module/jobs.py` | Partition aging, popular-post scoring |
| `post/service.py` | Interaction triggers (like, save, comment, share, view) |

### Schedulers that participate

| Job ID | Frequency | Function |
|--------|-----------|----------|
| `posts.expiry` | Every 1 hour | `run_expiry_job()` — ages partitions, soft-expires, hard-deletes |
| `posts.popular` | Every 15 min | `run_popular_posts_sync()` — recomputes velocity pool |
| `posts.taste_update` | Every 15 min | `run_taste_update_job()` — processes dwell events into taste |
| `posts.ignore_detect` | Daily 03:00 IST | `run_ignore_detection_job()` — repeated-ignore negative signals |

### APIs that participate

| Router prefix | File | Purpose |
|---------------|------|---------|
| `/posts` | `post/router.py` | CRUD, interactions (like/save/comment/share/view) |
| `/posts/recommendation` | `post_recommendation_module/router.py` | Feed, job triggers |
| `/posts/interactions` | `post_user_interaction/router.py` | Batch events, job triggers |

### System diagram

```
CLIENT
  │
  ├─ GET /posts/recommendation/feed
  │      └─ get_recommended_posts()
  │               ├─ UserEmbedding.post_feed_vector  (or build_user_feed_vector())
  │               ├─ taste_service.get_taste_weights()  →  user_post_taste
  │               ├─ seen_posts  (exclusion set)
  │               ├─ _query_partition()  →  post_embeddings (HNSW ANN)
  │               ├─ _get_popular_posts()  →  popular_posts
  │               ├─ _ensure_fresh_in_pool()  →  posts + post_embeddings
  │               ├─ _rerank()  →  posts, profile, user_connections
  │               ├─ _apply_diversity()
  │               └─ _build_feed_cards()  →  posts, profile, post_likes, post_saves, post_comments
  │
  ├─ POST /posts/interactions/batch
  │      └─ process_interaction_batch()
  │               ├─ post_interaction_events  (INSERT)
  │               └─ seen_posts  (ON CONFLICT DO NOTHING for dwell >= 3s)
  │
  ├─ POST /posts/{id}/like|save|comment|share
  │      └─ record_interaction()
  │               ├─ user_taste_profiles  (legacy counter UPDATE)
  │               └─ user_post_taste  (upsert: category + commodity + author)
  │
  └─ GET /posts/{id}
         └─ _record_view()
                  ├─ post_views  (INSERT, unique — fires revisit on duplicate)
                  ├─ posts.view_count  (UPDATE +1)
                  └─ record_revisit_event()  (on duplicate)
                           └─ record_interaction("revisit")

SCHEDULER (APScheduler)
  ├─ posts.taste_update  (15 min)  →  run_taste_update_job()
  │        ├─ post_interaction_events  (READ unprocessed dwell, MARK processed)
  │        ├─ user_taste_profiles  (UPDATE legacy counters)
  │        └─ user_post_taste  (UPSERT category + commodity + author)
  │
  ├─ posts.ignore_detect  (daily 03:00)  →  run_ignore_detection_job()
  │        ├─ post_interaction_events  (GROUP BY to find ignored pairs)
  │        └─ user_post_taste  (UPSERT negative deltas)
  │
  ├─ posts.popular  (15 min)  →  run_popular_posts_sync()
  │        ├─ posts  (READ engagement counters)
  │        ├─ post_embeddings  (READ active post IDs)
  │        └─ popular_posts  (DELETE ALL + bulk INSERT)
  │
  └─ posts.expiry  (1 hour)  →  run_expiry_job()
           └─ post_embeddings  (UPDATE partition, is_active; DELETE expired cold)
```

---

## Part 2 — Database Documentation

### Table: `posts`

**Purpose:** Master record for every published post. Holds content, metadata, counters, and location.

**Source file:** `app/modules/post/models.py`

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | Integer PK | No | Auto-increment |
| `profile_id` | Integer FK → `profile.id` | No | Author; CASCADE DELETE |
| `category_id` | Integer FK → `post_categories.id` | No | 1=Market Update, 2=Knowledge, 3=Discussion, 4=Deal/Req |
| `commodity_id` | Integer FK → `commodities.id` | No | 1=Rice, 2=Cotton, 3=Sugar |
| `title` | String(200) | No | Post title |
| `image_urls` | ARRAY(String) | Yes | List of storage URLs |
| `caption` | Text | No | Post body |
| `source_url` | String(500) | Yes | External reference link |
| `latitude` | Float | Yes | Post-specific geo; overrides author geo in vector when set |
| `longitude` | Float | Yes | |
| `location_name` | String(200) | Yes | Display label |
| `is_public` | Boolean | No | Default: true |
| `target_roles` | ARRAY(Integer) | Yes | Null = all roles; [1/2/3] = restricted |
| `allow_comments` | Boolean | No | Default: true |
| `like_count` | Integer | No | Denormalized counter; Default: 0 |
| `view_count` | Integer | No | Denormalized counter; Default: 0 |
| `comment_count` | Integer | No | Denormalized counter; Default: 0 |
| `share_count` | Integer | No | Denormalized counter; Default: 0 |
| `save_count` | Integer | No | Denormalized counter; Default: 0 |
| `created_at` | DateTime | No | UTC timestamp |

**Indexes:** Primary key on `id`. Implicit FK indexes on `profile_id`, `category_id`, `commodity_id`.

**Relationships:** Has one `PostDealDetails` (deal posts only). Has many `PostView`, `PostLike`, `PostComment`, `PostShare`, `PostSave`.

**Who writes:** `post/service.py` — create, update, delete, counter increments/decrements.

**Who reads:**
- `post_recommendation_module/service.py` — `_rerank()`, `_build_feed_cards()`, `_ensure_fresh_in_pool()`
- `post_recommendation_module/jobs.py` — `run_popular_posts_sync()` reads engagement counters
- `post_user_interaction/jobs.py` — `run_taste_update_job()` reads category/commodity/author per post

**Why it exists:** Single source of truth for post content and engagement counters.

---

### Table: `post_embeddings`

**Purpose:** Stores the 10-dimensional pgvector for each post plus partition state. The ANN index lives on this table.

**Source file:** `app/modules/post/post_recommendation_module/models.py`

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `post_id` | Integer PK FK → `posts.id` | No | CASCADE DELETE |
| `vector` | Vector(10) | No | pgvector — commodity[0:3], role[3:6], geo[6:9], qty[9] |
| `partition` | String(10) | No | "hot" \| "warm" \| "cold" |
| `is_active` | Boolean | No | False = expired; excluded from ANN |
| `expires_at` | DateTime(tz) | No | Category-specific expiry (2/7/14/90 days) |
| `category` | String(30) | No | Denormalized: "market_update" \| "knowledge" \| "discussion" \| "deal_req" |
| `commodity_idx` | Integer | No | 0=Cotton, 1=Rice, 2=Sugar |
| `created_at` | DateTime(tz) | No | UTC timestamp of embedding creation |

**Indexes:** Primary key on `post_id`. The HNSW ANN index is created separately in Alembic migration on the `vector` column using pgvector's `<=>` cosine distance operator.

**Who writes:**
- `post_recommendation_module/service.py` — `index_post()` on publish; `remove_post_index()` on delete/close
- `post_recommendation_module/jobs.py` — `run_expiry_job()` updates `partition` and `is_active`

**Who reads:**
- `post_recommendation_module/service.py` — `_query_partition()` executes ANN query
- `post_recommendation_module/jobs.py` — both jobs read this table for filtering

**Why it exists:** Separates the vector search concern from the post content. Enables HNSW ANN retrieval without touching the main posts table.

---

### Table: `popular_posts`

**Purpose:** Pre-computed pool of high-velocity posts per commodity. Refreshed every 15 minutes. Guarantees that trending posts surface even when they don't rank in ANN top-N.

**Source file:** `app/modules/post/post_recommendation_module/models.py`

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | Integer PK | No | Auto-increment |
| `post_id` | Integer FK → `posts.id` UNIQUE | No | CASCADE DELETE |
| `commodity_idx` | Integer (indexed) | No | 0=Cotton, 1=Rice, 2=Sugar |
| `category` | String(30) | No | Denormalized category string |
| `velocity_score` | Float | No | `(saves×3 + comments×2 + likes) / (hours+1)^1.5` |
| `saves_count` | Integer | No | Snapshot at sync time |
| `likes_count` | Integer | No | Snapshot at sync time |
| `comments_count` | Integer | No | Snapshot at sync time |
| `hours_since_post` | Float | No | Age in hours at sync time |
| `last_updated_at` | DateTime(tz) | No | |
| `is_active` | Boolean | No | Default: true |

**Indexes:** Primary key on `id`. Unique on `post_id`. B-tree on `commodity_idx`.

**Who writes:** `post_recommendation_module/jobs.py` — `run_popular_posts_sync()` does DELETE ALL + bulk INSERT every 15 minutes.

**Who reads:** `post_recommendation_module/service.py` — `_get_popular_posts()` queries by `commodity_idx IN (user's commodities)` and `is_active = true`, ordered by `velocity_score DESC`, limited to `POPULAR_LIMIT = 30`.

**Why it exists:** ANN retrieval can miss posts with low vector similarity that are nonetheless highly engaging. Popular posts provide a safety net.

---

### Table: `seen_posts`

**Purpose:** Tracks which posts each user has already seen. Posts in this table are excluded from the recommendation feed for 30 days.

**Source file:** `app/modules/post/post_recommendation_module/models.py`

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | Integer PK | No | Auto-increment |
| `profile_id` | Integer FK → `profile.id` | No | CASCADE DELETE |
| `post_id` | Integer FK → `posts.id` | No | CASCADE DELETE |
| `seen_at` | DateTime(tz) | No | UTC timestamp of first seen event |

**Constraints:** `UNIQUE (profile_id, post_id)` — named `uq_seen_post`.

**Who writes:**
- `post_user_interaction/service.py` — `process_interaction_batch()` upserts for dwell events with `value_ms >= DWELL_SEEN_MS (3000)` via raw SQL `ON CONFLICT DO NOTHING`
- `post_recommendation_module/service.py` — `record_seen()` called from `get_post()` (post detail open)

**Who reads:** `post_recommendation_module/service.py` — `_seen_post_ids()` queries `seen_at >= now - 30 days`.

**Why it exists:** Implements the 30-day exclusion window that prevents the same post from repeatedly appearing in the feed.

---

### Table: `post_views`

**Purpose:** Unique view log. One row per (post, profile) pair. The unique constraint enforces that each profile can only count one view per post.

**Source file:** `app/modules/post/models.py`

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | Integer PK | No | Auto-increment |
| `post_id` | Integer FK → `posts.id` | No | CASCADE DELETE |
| `profile_id` | Integer FK → `profile.id` | No | CASCADE DELETE |
| `viewed_at` | DateTime | No | UTC |

**Constraints:** `UNIQUE (post_id, profile_id)` — named `uq_post_view`.

**Who writes:** `post/service.py` — `_record_view()` attempts INSERT; on `IntegrityError` (duplicate) calls `record_revisit_event()` instead.

**Who reads:** Not read during recommendation. Used only for `view_count` display.

**Why it exists:** Enforces one view count per user per post and triggers the revisit signal on subsequent opens.

---

### Table: `post_likes`

**Purpose:** Like ledger. One row per (post, profile) like event.

**Source file:** `app/modules/post/models.py`

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | Integer PK | No | |
| `post_id` | Integer FK → `posts.id` | No | CASCADE DELETE |
| `profile_id` | Integer FK → `profile.id` | No | CASCADE DELETE |
| `liked_at` | DateTime | No | UTC |

**Constraints:** `UNIQUE (post_id, profile_id)` — named `uq_post_like`.

**Who writes:** `post/service.py` — `toggle_like()` inserts on like, deletes on unlike.

**Who reads:** `post_recommendation_module/service.py` — `_build_feed_cards()` queries `PostLike` by `post_id IN (feed_ids)` and `profile_id = viewer` to populate `is_liked`.

**Why it exists:** Source of truth for the like state and `like_count` denominator.

---

### Table: `post_saves`

**Purpose:** Save ledger. One row per (post, profile) save event.

**Source file:** `app/modules/post/models.py`

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | Integer PK | No | |
| `post_id` | Integer FK → `posts.id` | No | CASCADE DELETE |
| `profile_id` | Integer FK → `profile.id` | No | CASCADE DELETE |
| `saved_at` | DateTime | No | UTC |

**Constraints:** `UNIQUE (post_id, profile_id)` — named `uq_post_save`.

**Who writes:** `post/service.py` — `toggle_save()`.

**Who reads:** `post_recommendation_module/service.py` — `_build_feed_cards()` populates `is_saved`.

**Why it exists:** Save is the highest-weight persistent taste signal (+5.0). Also powers the `/posts/saved` personal bookmarks feed.

---

### Table: `post_comments`

**Purpose:** Comment store.

**Source file:** `app/modules/post/models.py`

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | Integer PK | No | |
| `post_id` | Integer FK → `posts.id` | No | CASCADE DELETE |
| `profile_id` | Integer FK → `profile.id` | No | CASCADE DELETE |
| `content` | Text | No | |
| `created_at` | DateTime | No | UTC |

**Who writes:** `post/service.py` — `add_comment()`, `delete_comment()`.

**Who reads:** `post_recommendation_module/service.py` — `_build_feed_cards()` fetches the latest comment per post via a `MAX(id)` subquery to populate `comment_preview_author` and `comment_preview_text`.

---

### Table: `post_shares`

**Purpose:** Share log (non-unique — multiple shares per user per post are allowed).

**Source file:** `app/modules/post/models.py`

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | Integer PK | No | |
| `post_id` | Integer FK → `posts.id` | No | CASCADE DELETE |
| `profile_id` | Integer FK → `profile.id` | No | CASCADE DELETE |
| `shared_at` | DateTime | No | UTC |

**No unique constraint** — each call to `record_share()` inserts a new row.

**Who writes:** `post/service.py` — `record_share()`.

**Who reads:** Not directly read during recommendation. `share_count` on `posts` is used.

---

### Table: `post_interaction_events`

**Purpose:** Append-only event log for all behavioural signals. Primary data source for the async taste update jobs.

**Source file:** `app/modules/post/post_user_interaction/models.py`

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | Integer PK | No | Auto-increment |
| `profile_id` | Integer FK → `profile.id` | No | CASCADE DELETE |
| `post_id` | Integer FK → `posts.id` | No | CASCADE DELETE |
| `event_type` | String(30) | No | impression \| dwell \| open_read_more \| open_carousel \| open_comments \| link_click \| revisit |
| `value_ms` | Integer | Yes | Dwell duration in ms; NULL for non-dwell events |
| `occurred_at` | DateTime(tz) | No | Client-provided timestamp of the event |
| `created_at` | DateTime(tz) | No | Server insert time |
| `processed_at` | DateTime(tz) | Yes | NULL = not yet processed by taste job; set to now when job processes |

**Indexes:**
- `ix_pie_profile_post` on `(profile_id, post_id)` — used by ignore detection GROUP BY
- `ix_pie_event_type_created` on `(event_type, created_at)` — range queries by type + time
- `ix_pie_created_at` on `created_at`
- `ix_pie_event_type_processed` on `(event_type, processed_at)` — used by taste update job to find unprocessed dwell events

**Who writes:**
- `post_user_interaction/service.py` — `process_interaction_batch()` bulk inserts; `record_revisit_event()` inserts single revisit
- `post_user_interaction/jobs.py` — updates `processed_at` when events are consumed

**Who reads:**
- `post_user_interaction/jobs.py` — `run_taste_update_job()` reads unprocessed dwell events; `run_ignore_detection_job()` aggregates by (profile_id, post_id)

**Why it exists:** Decouples signal ingestion (synchronous, high frequency) from taste computation (asynchronous, batched). Enables replay and analytics.

---

### Table: `user_post_taste`

**Purpose:** Row-per-dimension persistent taste store. Active read path for the recommendation reranker (Phase 7+). Holds float scores with separate positive and negative accumulators.

**Source file:** `app/modules/post/post_user_interaction/models.py`

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `profile_id` | Integer FK → `profile.id` PK | No | CASCADE DELETE |
| `dimension_type` | String(20) PK | No | "category" \| "commodity" \| "author" |
| `dimension_key` | String(50) PK | No | Category name, commodity_id (str), or author profile_id (str) |
| `positive_score` | Float | No | Accumulated positive signal weight |
| `negative_score` | Float | No | Accumulated negative signal weight |
| `event_count` | Integer | No | Number of contributing events |
| `last_event_at` | DateTime(tz) | No | Timestamp of most recent update |

**Composite PK:** `(profile_id, dimension_type, dimension_key)`

**Indexes:** `ix_upt_profile_type` on `(profile_id, dimension_type)` — primary read access pattern.

**Who writes:**
- `post_user_interaction/taste_service.py` — `update_taste()` via `pg_insert.on_conflict_do_update`
- Called from: `service.record_interaction()` (synchronous, like/save/comment/share), `jobs.run_taste_update_job()` (async, dwell events), `jobs.run_ignore_detection_job()` (async, negative signals)

**Who reads:** `post_user_interaction/taste_service.py` — `get_taste_weights()` called three times per feed request (category, commodity, author).

**Why it exists:** Replaces `user_taste_profiles` as the taste read path. Supports float scores (vs integers), multiple dimensions (vs category-only), negative signals, and query-time decay.

---

### Table: `user_taste_profiles`

**Purpose:** Legacy flat-counter taste table. Still receives dual-writes from all interaction paths. No longer read by the reranker as of Phase 7.

**Source file:** `app/modules/post/post_user_interaction/models.py`

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `profile_id` | Integer FK → `profile.id` PK | No | CASCADE DELETE |
| `market_update_count` | Integer | No | Default 0 |
| `deal_req_count` | Integer | No | Default 0 |
| `discussion_count` | Integer | No | Default 0 |
| `knowledge_count` | Integer | No | Default 0 |
| `total_events` | Integer | No | Interaction event counter |
| `updated_at` | DateTime(tz) | No | Auto-updated |

**Who writes:**
- `post_user_interaction/service.py` — `record_interaction()` for synchronous signals
- `post_user_interaction/jobs.py` — `run_taste_update_job()` for dwell signals

**Who reads:** `post_user_interaction/service.py` — `get_taste_for_feed()` (no longer called by the reranker; retained for legacy compatibility).

---

### Table: `user_embeddings` (read-only for recommendation)

**Purpose:** Stores pre-built user vectors. The `post_feed_vector` column (10-dim) is read at feed request time to avoid recomputing the vector on every call.

**Source file:** `app/modules/profile/models.py`

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `user_id` | UUID PK FK → `users.id` | No | CASCADE DELETE |
| `is_vector` | Vector(11) | Yes | Connection recommendation vector (not used by post rec) |
| `post_feed_vector` | Vector(10) | Yes | Post feed user vector — read by recommendation service |
| `updated_at` | DateTime | No | UTC |

**Who reads:** `post_recommendation_module/service.py` — `get_recommended_posts()` reads `post_feed_vector`; falls back to `build_user_feed_vector()` if NULL.

**Who writes:** Profile service (outside post recommendation scope). Post recommendation never writes this table.

---

## Part 3 — User Interaction Lifecycle

### 3.1 View

**Trigger:** User opens post detail page.

```
User
  └─ GET /posts/{post_id}
        └─ post/router.py: get_post_api()
              └─ post/service.py: get_post()
                    ├─ _get_post_or_raise()  [SELECT posts WHERE id=post_id AND profile_id IN active]
                    ├─ _record_view()
                    │     ├─ INSERT INTO post_views (post_id, profile_id)
                    │     ├─ [success path]
                    │     │     └─ UPDATE posts SET view_count = view_count + 1
                    │     └─ [IntegrityError — duplicate view]
                    │           └─ record_revisit_event()
                    │                 ├─ INSERT INTO post_interaction_events (event_type='revisit', processed_at=now)
                    │                 └─ record_interaction(profile_id, post.category_id, "revisit", post.commodity_id, post.profile_id)
                    │                       ├─ UPDATE user_taste_profiles (category_col += 6, total_events += 1)
                    │                       └─ UPSERT user_post_taste (category +6.0, commodity +6.0, author +6.0)
                    ├─ rec_service.record_seen()
                    │     └─ INSERT INTO seen_posts (profile_id, post_id)  [with try/except IntegrityError]
                    └─ RETURN PostResponse
```

**DB writes:**
- `post_views`: INSERT (unique; IntegrityError on duplicate)
- `posts.view_count`: INCREMENT by 1 (first view only)
- On revisit: `post_interaction_events` INSERT; `user_taste_profiles` UPDATE; `user_post_taste` UPSERT
- `seen_posts`: INSERT ON CONFLICT IGNORED

**Signal weight:** revisit = +6.0 (strongest signal; `SIGNAL_WEIGHTS["revisit"]` in constants.py)

**Counter updated:** `posts.view_count` +1 on first view only.

---

### 3.2 Like

**Trigger:** User taps the like button.

```
User
  └─ POST /posts/{post_id}/like
        └─ post/router.py: toggle_like_api()
              └─ post/service.py: toggle_like()
                    ├─ _get_post_or_raise()
                    ├─ [unlike path — existing PostLike found]
                    │     ├─ DELETE FROM post_likes WHERE post_id=? AND profile_id=?
                    │     └─ UPDATE posts SET like_count = like_count - 1
                    │     [No taste update on unlike]
                    └─ [like path — no existing PostLike]
                          ├─ INSERT INTO post_likes (post_id, profile_id)
                          ├─ UPDATE posts SET like_count = like_count + 1
                          └─ record_interaction(profile_id, post.category_id, "like", post.commodity_id, post.profile_id)
                                ├─ derive_signal("like", None) → (3.0, 0.0)
                                ├─ _to_int_delta(3.0) → 3
                                ├─ UPDATE user_taste_profiles SET {category_col} += 3, total_events += 1
                                ├─ UPSERT user_post_taste: category/like_category pos += 3.0
                                ├─ UPSERT user_post_taste: commodity/str(commodity_id) pos += 3.0
                                └─ UPSERT user_post_taste: author/str(author_profile_id) pos += 3.0
                                   [only if author != viewer AND pos_delta >= AUTHOR_TASTE_MIN_DELTA (2.0)]
```

**DB writes:**
- `post_likes`: INSERT or DELETE
- `posts.like_count`: ±1
- On like only: `user_taste_profiles` UPDATE; `user_post_taste` UPSERT ×3

**Signal weight:** like = +3.0 (`SIGNAL_WEIGHTS["like"]`)

**Counter updated:** `posts.like_count` ±1

---

### 3.3 Save

**Trigger:** User taps the save/bookmark button.

```
User
  └─ POST /posts/{post_id}/save
        └─ post/router.py: toggle_save_api()
              └─ post/service.py: toggle_save()
                    ├─ _get_post_or_raise()
                    ├─ [unsave path]
                    │     ├─ DELETE FROM post_saves WHERE post_id=? AND profile_id=?
                    │     └─ UPDATE posts SET save_count = save_count - 1
                    │     [No taste update on unsave]
                    └─ [save path]
                          ├─ INSERT INTO post_saves (post_id, profile_id)
                          ├─ UPDATE posts SET save_count = save_count + 1
                          └─ record_interaction(..., "save", ...)
                                ├─ derive_signal("save", None) → (5.0, 0.0)
                                ├─ _to_int_delta(5.0) → 5
                                ├─ UPDATE user_taste_profiles: category_col += 5, total_events += 1
                                ├─ UPSERT user_post_taste: category pos += 5.0
                                ├─ UPSERT user_post_taste: commodity pos += 5.0
                                └─ UPSERT user_post_taste: author pos += 5.0  [if eligible]
```

**Signal weight:** save = +5.0 (highest explicit signal; `SIGNAL_WEIGHTS["save"]`)

---

### 3.4 Comment

**Trigger:** User submits a comment.

```
User
  └─ POST /posts/{post_id}/comments
        └─ post/router.py: add_comment_api()
              └─ post/service.py: add_comment()
                    ├─ _get_post_or_raise()
                    ├─ CommentsDisabledError if post.allow_comments == False
                    ├─ INSERT INTO post_comments (post_id, profile_id, content)
                    ├─ UPDATE posts SET comment_count = comment_count + 1
                    └─ record_interaction(..., "comment", post.commodity_id, post.profile_id)
                          ├─ derive_signal("comment", None) → (4.0, 0.0)
                          ├─ UPDATE user_taste_profiles: category_col += 4, total_events += 1
                          ├─ UPSERT user_post_taste: category pos += 4.0
                          ├─ UPSERT user_post_taste: commodity pos += 4.0
                          └─ UPSERT user_post_taste: author pos += 4.0  [if eligible]
```

**Signal weight:** comment = +4.0 (`SIGNAL_WEIGHTS["comment"]`)

---

### 3.5 Share

**Trigger:** User taps the share button.

```
User
  └─ POST /posts/{post_id}/share
        └─ post/router.py: record_share_api()
              └─ post/service.py: record_share()
                    ├─ _get_post_or_raise()
                    ├─ INSERT INTO post_shares (post_id, profile_id)   [non-unique — each share is a new row]
                    ├─ UPDATE posts SET share_count = share_count + 1
                    └─ record_interaction(..., "share", post.commodity_id, post.profile_id)
                          ├─ derive_signal("share", None) → (4.0, 0.0)
                          ├─ UPDATE user_taste_profiles: category_col += 4, total_events += 1
                          ├─ UPSERT user_post_taste: category pos += 4.0
                          ├─ UPSERT user_post_taste: commodity pos += 4.0
                          └─ UPSERT user_post_taste: author pos += 4.0  [if eligible]
```

**Signal weight:** share = +4.0 (`SIGNAL_WEIGHTS["share"]`)

---

## Part 4 — User Taste Profile

### 4.1 The Two Tables

There are two taste stores in parallel:

| | `user_taste_profiles` | `user_post_taste` |
|---|---|---|
| Type | Legacy flat-counter | Active row-per-dimension |
| Score type | Integer | Float |
| Dimensions | Category only | Category + Commodity + Author |
| Negative scores | None | Yes (separate column) |
| Decay | None | Query-time exponential |
| Reranker read path | No (since Phase 7) | Yes |
| Still written | Yes (dual-write) | Yes |

### 4.2 `user_taste_profiles` — How It Works

**Creation:** Created lazily in `record_interaction()` when a user's first explicit interaction occurs (like/save/comment/share). Initialized with role-seeded defaults:

```python
# constants.py
DEFAULT_TASTE: dict[int, dict[str, int]] = {
    1: {"deal_req": 100, "market_update": 80,  "discussion": 20, "knowledge": 20},  # Trader
    2: {"deal_req": 100, "market_update": 60,  "discussion": 50, "knowledge": 30},  # Broker
    3: {"deal_req": 60,  "market_update": 100, "knowledge": 50,  "discussion": 20},  # Exporter
}
```

**Column mapping:**
```python
# service.py
_CATEGORY_COL_MAP = {
    "market_update": "market_update_count",
    "deal_req":      "deal_req_count",
    "discussion":    "discussion_count",
    "knowledge":     "knowledge_count",
}
```

**Update on interaction:**
```python
int_delta = _to_int_delta(pos_delta)  # round-half-up
setattr(taste, col, getattr(taste, col) + int_delta)
taste.total_events += 1
```

The `_to_int_delta()` function uses `int(value + 0.5)` (round-half-up). Examples:
- save (+5.0) → 5
- like (+3.0) → 3
- dwell_medium (+2.0) → 2
- dwell_short (+0.5) → 1

**`total_events` semantics:** Incremented by 1 per `record_interaction()` call regardless of the signal weight. Used only for confidence blend threshold check.

### 4.3 `user_post_taste` — How It Works

**Upsert mechanism (`taste_service.update_taste`):**

```python
stmt = (
    pg_insert(UserPostTaste.__table__)
    .values(profile_id=..., dimension_type=..., dimension_key=...,
            positive_score=positive_delta, negative_score=negative_delta,
            event_count=event_count, last_event_at=now)
    .on_conflict_do_update(
        index_elements=["profile_id", "dimension_type", "dimension_key"],
        set_={
            "positive_score": table.c.positive_score + positive_delta,
            "negative_score": table.c.negative_score + negative_delta,
            "event_count":    table.c.event_count + event_count,
            "last_event_at":  now,
        }
    )
)
```

This is a single atomic SQL statement. On INSERT: sets scores to the delta values. On CONFLICT (row already exists): adds deltas to existing scores. The caller commits.

### 4.4 Reading Taste Weights — `get_taste_weights()`

Source: `post_user_interaction/taste_service.py`

**Step 1: Query rows**
```python
rows = db.query(UserPostTaste).filter(
    UserPostTaste.profile_id == profile_id,
    UserPostTaste.dimension_type == dimension_type,
).all()
```

**Step 2: Cold-start fallback**
If no rows exist and `dimension_type == "category"`:
```python
return {k: float(v) for k, v in DEFAULT_TASTE.get(role_id, DEFAULT_TASTE[1]).items()}
```
For non-category dimensions with no rows: return `{}`.

**Step 3: Apply exponential decay**
```python
days_since = (now - row.last_event_at).total_seconds() / 86400
decayed = row.positive_score * math.exp(-TASTE_DECAY_LAMBDA * days_since)
# TASTE_DECAY_LAMBDA = 0.023  (source: constants.py)
# Half-life = ln(2) / 0.023 ≈ 30.1 days
```

**Step 4: Net score with negative discount**
```python
_NEG_DISCOUNT = 0.6   # source: taste_service.py
net = decayed - (row.negative_score * _NEG_DISCOUNT)
scores[row.dimension_key] = max(net, _SCORE_FLOOR)   # _SCORE_FLOOR = 0.05
```

**Step 5: Confidence blend (category only)**
```python
# TASTE_BOOTSTRAP_EVENTS = 20  (source: constants.py)
if dimension_type == "category" and role_id is not None and total_events < TASTE_BOOTSTRAP_EVENTS:
    defaults = DEFAULT_TASTE.get(role_id, DEFAULT_TASTE[1])
    confidence = total_events / TASTE_BOOTSTRAP_EVENTS
    for key, default_val in defaults.items():
        learned = scores.get(key, _SCORE_FLOOR)
        scores[key] = confidence * learned + (1 - confidence) * float(default_val)
```

### 4.5 Worked Example — Taste Calculation

**Setup:** Trader (role_id=1), 3 interactions so far: 2 discussions (liked), 1 market_update (liked). No time has elapsed since interactions (days_since = 0).

**State of `user_post_taste` after interactions:**

| profile_id | dimension_type | dimension_key | positive_score | negative_score | event_count |
|------------|---------------|---------------|---------------|---------------|-------------|
| 7 | category | discussion | 6.0 | 0.0 | 2 |
| 7 | category | market_update | 3.0 | 0.0 | 1 |

**`get_taste_weights(db, 7, "category", role_id=1)`:**

Step 1: Two rows returned (discussion=6.0, market_update=3.0). No deal_req or knowledge rows.

Step 2: Not cold-start (rows exist).

Step 3: days_since=0 → decay factor = exp(0) = 1.0. No change.

Step 4: Net scores (no negative scores):
- discussion: max(6.0, 0.05) = 6.0
- market_update: max(3.0, 0.05) = 3.0

Step 5: total_events = 3 (< 20), confidence = 3/20 = 0.15. Blend with Trader defaults:
- deal_req:      0.15 × 0.05 + 0.85 × 100 = 0.0075 + 85.0  = **85.01**
- market_update: 0.15 × 3.0  + 0.85 × 80  = 0.45   + 68.0  = **68.45**
- discussion:    0.15 × 6.0  + 0.85 × 20  = 0.90   + 17.0  = **17.90**
- knowledge:     0.15 × 0.05 + 0.85 × 20  = 0.0075 + 17.0  = **17.01**

**Returned `cat_weights`:**
```python
{
    "deal_req":      85.01,
    "market_update": 68.45,
    "discussion":    17.90,
    "knowledge":     17.01
}
```

**`_category_weight()` normalization in reranker:**
```python
total = log1p(85.01) + log1p(68.45) + log1p(17.90) + log1p(17.01)
      = 4.454         + 4.228        + 2.944         + 2.888
      = 14.514

weight("deal_req")      = log1p(85.01)  / 14.514 = 4.454 / 14.514 = 0.307
weight("market_update") = log1p(68.45)  / 14.514 = 4.228 / 14.514 = 0.291
weight("discussion")    = log1p(17.90)  / 14.514 = 2.944 / 14.514 = 0.203
weight("knowledge")     = log1p(17.01)  / 14.514 = 2.888 / 14.514 = 0.199
```

**Interpretation:** Despite 2 discussion likes, role-seeded defaults dominate at confidence=0.15. Deal/req posts still get 0.307 weight because the Trader default (100) is very strong. After 20+ interactions, learned taste will fully control the weights.

**After 30 days with no new interactions:**
- days_since = 30
- decay factor = exp(-0.023 × 30) = exp(-0.69) ≈ 0.501
- discussion.decayed = 6.0 × 0.501 = 3.006
- market_update.decayed = 3.0 × 0.501 = 1.503

The scores halve roughly every 30 days, pulling the blend back toward role defaults.

---

## Part 5 — Recommendation Request Lifecycle

### Complete method call trace

```
GET /posts/recommendation/feed?limit=25
  └─ post_recommendation_module/router.py: get_feed()
        └─ post_recommendation_module/service.py: get_recommended_posts(db, profile_id, limit=25)
```

**Step 1: Load profile**
```python
profile = db.query(Profile).filter(Profile.id == profile_id).first()
# Raises ValueError (→ 404) if not found
```

**Step 2: Extract commodity indexes**
```python
commodity_ids = [pc.commodity_id for pc in profile.commodities]
commodity_idxs = {COMMODITY_ID_TO_IDX[cid] for cid in commodity_ids if cid in COMMODITY_ID_TO_IDX}
# COMMODITY_ID_TO_IDX = {1: 1, 2: 0, 3: 2}  (Rice→1, Cotton→0, Sugar→2)
```

**Step 3: Resolve user vector**
```python
emb_row = db.query(UserEmbedding).filter(UserEmbedding.user_id == profile.users_id).first()
if emb_row and emb_row.post_feed_vector is not None:
    user_vec = _parse_vec(emb_row.post_feed_vector)
else:
    user_vec = build_user_feed_vector(
        commodity_ids=commodity_ids,
        role_id=profile.role_id,
        lat=float(profile.business.latitude),
        lon=float(profile.business.longitude),
        commodity_quantity=(float(profile.quantity_min) + float(profile.quantity_max)) / 2,
    )
```

**Step 4: Load taste weights (3 queries)**
```python
cat_weights       = taste_service.get_taste_weights(db, profile_id, "category", profile.role_id)
commodity_weights = taste_service.get_taste_weights(db, profile_id, "commodity")
author_weights    = taste_service.get_taste_weights(db, profile_id, "author")
```

**Step 5: Load followed user IDs**
```python
followed_user_ids = {
    row.following_id
    for row in db.query(UserConnection.following_id)
    .filter(UserConnection.follower_id == profile.users_id)
    .all()
}
```

**Step 6: Load seen post IDs**
```python
cutoff = datetime.now(timezone.utc) - timedelta(days=30)
seen_ids = {r[0] for r in db.query(SeenPost.post_id)
    .filter(SeenPost.profile_id == profile_id, SeenPost.seen_at >= cutoff).all()}
pool_exclude = set(seen_ids)
```

**Step 7: ANN retrieval — hot partition**
```python
# FETCH_TARGET = 150
hot_embs = _query_partition(db, "hot", FETCH_TARGET, pool_exclude, user_vec)
for emb in hot_embs:
    score = weighted_cosine_similarity(user_vec, emb["vector"])
    pool.append({"post_id": ..., "category": ..., "vec_score": score})
    pool_exclude.add(emb["post_id"])
```

**Step 8: ANN retrieval — warm + cold (conditional)**
```python
# MIN_POOL_SIZE = 80
if len(pool) < MIN_POOL_SIZE:
    warm_embs = _query_partition(db, "warm", FETCH_TARGET - len(pool), pool_exclude, user_vec)
    # same loop...
if len(pool) < MIN_POOL_SIZE:
    cold_embs = _query_partition(db, "cold", FETCH_TARGET - len(pool), pool_exclude, user_vec)
```

**Step 9: Popular posts**
```python
# POPULAR_LIMIT = 30
popular = _get_popular_posts(db, commodity_idxs or {0, 1, 2}, pool_exclude)
pool.extend(popular)
```

**Step 10: Fresh post injection**
```python
# FRESH_SLOTS = 5, FRESH_INJECT_HOURS = 4
fresh = _ensure_fresh_in_pool(db, profile.role_id, commodity_idxs or {0,1,2}, pool_exclude, user_vec, FRESH_SLOTS)
pool.extend(fresh)
```

**Step 11: Rerank**
```python
scored = _rerank(db, pool, cat_weights, commodity_weights, author_weights, followed_user_ids)
```

**Step 12: Diversity filter**
```python
# FEED_SIZE = 25, MAX_PER_CATEGORY = 8, MAX_PER_AUTHOR = 3
final = _apply_diversity(scored, limit=limit)
```

**Step 13: Build response cards**
```python
return _build_feed_cards(db, final, profile_id)
```

### Full sequence diagram

```
Client          Router           Service          DB
  │               │                │               │
  ├─GET /feed────►│                │               │
  │               ├─get_rec_posts─►│               │
  │               │                ├─SELECT Profile─────────────────────────►│
  │               │                ├─SELECT UserEmbedding────────────────────►│
  │               │                ├─SELECT UserPostTaste (category)──────────►│
  │               │                ├─SELECT UserPostTaste (commodity)─────────►│
  │               │                ├─SELECT UserPostTaste (author)────────────►│
  │               │                ├─SELECT UserConnection (following)─────────►│
  │               │                ├─SELECT SeenPost (30-day window)───────────►│
  │               │                ├─ANN: post_embeddings WHERE partition='hot'─►│
  │               │                ├─[if pool < 80] ANN warm──────────────────►│
  │               │                ├─[if pool < 80] ANN cold──────────────────►│
  │               │                ├─SELECT popular_posts──────────────────────►│
  │               │                ├─SELECT posts+post_embeddings (fresh < 4h)──►│
  │               │                ├─_rerank()                │               │
  │               │                │   ├─SELECT Post (bulk)───────────────────►│
  │               │                │   └─SELECT Profile (authors)──────────────►│
  │               │                ├─_apply_diversity()       │               │
  │               │                ├─_build_feed_cards()      │               │
  │               │                │   ├─SELECT PostLike──────────────────────►│
  │               │                │   ├─SELECT PostSave──────────────────────►│
  │               │                │   └─SELECT PostComment (latest per post)──►│
  │◄─FeedResponse─┤◄───────────────┤               │               │
```

---

## Part 6 — Candidate Retrieval

### The `_query_partition()` function

Source: `post_recommendation_module/service.py`

```python
def _query_partition(db, partition, limit, exclude_ids, user_vec):
    vec_str = "[" + ",".join(str(v) for v in user_vec) + "]"
    exclude_clause = f"AND post_id NOT IN ({','.join(str(i) for i in exclude_ids)})" if exclude_ids else ""

    rows = db.execute(text(f"""
        SELECT post_id, category, vector
        FROM post_embeddings
        WHERE partition = :partition
          AND is_active = true
          {exclude_clause}
        ORDER BY vector <=> CAST(:vec AS vector)
        LIMIT :limit
    """), {"vec": vec_str, "partition": partition, "limit": limit}).mappings().all()
```

`<=>` is pgvector's cosine distance operator. The HNSW index on `post_embeddings.vector` enables approximate nearest-neighbor search at O(log N) cost.

**Note on exact vs approximate similarity:** `_query_partition()` returns raw vectors. The ANN retrieval gives an approximation. The caller then recomputes exact `weighted_cosine_similarity()` and uses that as `vec_score`. The ANN is only used for candidate narrowing — the exact similarity is computed in Python post-retrieval.

### Partition system

**Why partitions exist:** The HNSW index is scanned for the entire partition. Partitioning by recency limits the scan space for the most relevant posts.

| Partition | Age range (post creation time) | Allowed categories |
|-----------|-------------------------------|--------------------|
| `hot` | 0 – 72 h | market_update, deal_req, knowledge, discussion |
| `warm` | 72 – 120 h | deal_req, knowledge, discussion |
| `cold` | 120 – 720 h | knowledge, discussion |

Constants: `HOT_MAX_HOURS=72`, `WARM_MAX_HOURS=120`, `COLD_MAX_HOURS=720` (`constants.py`)

Market Update posts expire into `warm` at 72h because `PARTITION_ALLOWED["warm"]` does not include `"market_update"`. They are soft-expired (`is_active=False`) by `run_expiry_job()` at their `expires_at` timestamp (2 days from creation).

**Sequential fallback:**
```
Try hot  → pool size check (MIN_POOL_SIZE = 80)
  If < 80: try warm → pool size check
    If < 80: try cold
```

Each partition is queried with `limit = FETCH_TARGET - current_pool_size`. `FETCH_TARGET = 150`.

**Popular posts bypass:** Always appended to pool regardless of pool size. Not subject to ANN or partition.

### `_get_popular_posts()` — popular post injection

```python
q = db.query(PopularPost).filter(
    PopularPost.commodity_idx.in_(list(commodity_idxs)),
    PopularPost.is_active == True,
)
if exclude_ids:
    q = q.filter(~PopularPost.post_id.in_(list(exclude_ids)))
rows = q.order_by(PopularPost.velocity_score.desc()).limit(POPULAR_LIMIT).all()
return [{"post_id": r.post_id, "category": r.category, "vec_score": 0.5} for r in rows]
```

Popular posts enter the pool with a **fixed `vec_score = 0.5`**. They still undergo full reranking with taste, engagement, freshness, and social multipliers applied.

---

## Part 7 — Freshness Logic

### Fresh post guarantee — `_ensure_fresh_in_pool()`

Source: `post_recommendation_module/service.py`

**Purpose:** The HNSW ANN retrieves approximate nearest neighbors within a partition. A recently published post may have a lower similarity score than older posts and could be pushed out of the top-150 results even if it is relevant. The fresh pool guarantee bypasses the ANN for posts younger than `FRESH_INJECT_HOURS = 4` hours.

```python
def _ensure_fresh_in_pool(db, viewer_role_id, commodity_idxs, exclude_ids, user_vec, limit):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=FRESH_INJECT_HOURS)  # 4 hours

    rows = db.execute(text(f"""
        SELECT pe.post_id, pe.category, pe.vector, p.target_roles
        FROM post_embeddings pe
        JOIN posts p ON p.id = pe.post_id
        WHERE pe.is_active = true
          AND p.created_at >= :cutoff
          AND p.is_public = true
          {commodity_clause}
          {exclude_clause}
        ORDER BY p.created_at DESC
        LIMIT :limit
    """), {"cutoff": cutoff, "limit": limit * 3}).mappings().all()

    result = []
    for r in rows:
        target = r["target_roles"]
        if target and viewer_role_id not in target:
            continue
        vec_score = weighted_cosine_similarity(user_vec, _parse_vec(r["vector"]))
        result.append({"post_id": r["post_id"], "category": r["category"], "vec_score": vec_score})
        if len(result) >= limit:
            break
    return result
```

- Fetches `limit * 3 = 15` candidates from posts younger than 4h, filtered by commodity
- Applies `target_roles` visibility check per post
- Computes exact `weighted_cosine_similarity()` for each
- Returns at most `FRESH_SLOTS = 5` candidates

These candidates enter the pool and compete through full reranking. Their advantage is the freshness multiplier applied during `_rerank()`.

### Freshness multiplier — `_freshness()`

Source: `post_recommendation_module/service.py`

```python
def _freshness(created_at: datetime) -> float:
    age_h = max(0.0, (datetime.now(timezone.utc) - created_at).total_seconds() / 3600)
    return 1.0 + FRESH_BOOST_PEAK * math.exp(-age_h / FRESH_DECAY_TAU)
    # FRESH_BOOST_PEAK = 0.4  (source: constants.py)
    # FRESH_DECAY_TAU  = 8.0  (source: constants.py)
```

**Formula:** `f(age) = 1.0 + 0.4 × e^(−age_h / 8.0)`

**Numerical values:**

| Post age | Multiplier |
|----------|-----------|
| 0 h (just published) | 1.0 + 0.4 × 1.000 = **1.400** |
| 2 h | 1.0 + 0.4 × 0.779 = **1.312** |
| 4 h | 1.0 + 0.4 × 0.607 = **1.243** |
| 8 h | 1.0 + 0.4 × 0.368 = **1.147** |
| 12 h | 1.0 + 0.4 × 0.223 = **1.089** |
| 24 h | 1.0 + 0.4 × 0.050 = **1.020** |
| 48 h | 1.0 + 0.4 × 0.003 = **1.001** |

**Interpretation:** A brand-new post scores 40% higher than an identical post that is 48+ hours old. The boost follows exponential decay with a time constant of 8 hours (~5.5h half-life for the boost portion). By 48 hours the freshness contribution is effectively zero.

---

## Part 8 — Reranking Logic

### The `_rerank()` function

Source: `post_recommendation_module/service.py`

**Inputs:**
- `candidates`: list of `{post_id, category, vec_score}` dicts from ANN + popular + fresh pools
- `cat_weights`: `dict[str, float]` from `taste_service.get_taste_weights(..., "category")`
- `commodity_weights`: `dict[str, float]` from `taste_service.get_taste_weights(..., "commodity")`
- `author_weights`: `dict[str, float]` from `taste_service.get_taste_weights(..., "author")`
- `followed_user_ids`: `set` of user UUIDs the viewer follows

**Output:** List of `{post_id, category, author_profile_id, final_score}` sorted descending.

### Factor 1: Vector Similarity (`vec_score`)

**Source:** `weighted_cosine_similarity()` in `vector.py`

```python
def weighted_cosine_similarity(u, v):
    w = np.array(FEED_WEIGHTS)      # [3,3,3, 2,2,2, 1.5,1.5,1.5, 1.0]
    a = np.array(u) * w
    b = np.array(v) * w
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / norm) if norm != 0 else 0.0
```

**`FEED_WEIGHTS` (constants.py):**
```
[3.0, 3.0, 3.0,    # dims 0-2: commodity (highest weight)
 2.0, 2.0, 2.0,    # dims 3-5: role
 1.5, 1.5, 1.5,    # dims 6-8: geo
 1.0]              # dim 9:   quantity
```

The weight vector is applied to both vectors before computing cosine similarity, giving commodity matching 3× more influence than quantity matching.

**Range:** [−1, 1] in theory; in practice [0, ~0.95] for this domain since all vector components are non-negative.

**Popular posts exception:** Fixed `vec_score = 0.5` (assigned in `_get_popular_posts()`).

### Factor 2: Category Weight (`_category_weight()`)

```python
def _category_weight(cat_weights, category):
    total = sum(math.log1p(v) for v in cat_weights.values())
    if total == 0:
        return 1.0 / max(len(cat_weights), 1)
    return math.log1p(cat_weights.get(category, 0.05)) / total
```

**Inputs:** `cat_weights` from `get_taste_weights(..., "category")` — decayed, confidence-blended scores.

**Transformation:** log1p normalization. log1p compresses large differences (e.g., 85 vs 17 → 4.45 vs 2.94 rather than a 5× ratio). The division by total normalizes weights so they sum to 1.0.

**Range:** (0, 1) — always positive due to log1p floor of 0.05.

**Fallback for unknown category:** `cat_weights.get(category, 0.05)` — uses floor score of 0.05 if a category has no taste data (not possible with current 4-category system since confidence blend always fills all 4).

### Factor 3: Commodity Multiplier (`_commodity_multiplier()`)

```python
def _commodity_multiplier(commodity_weights, commodity_id):
    if not commodity_id or not commodity_weights:
        return 1.0
    score = commodity_weights.get(str(commodity_id), 0.0)
    if score <= 0:
        return 1.0
    max_score = max(commodity_weights.values())
    return 1.0 + 0.3 * min(score / max(max_score, 0.05), 1.0)
```

**Range:** [1.0, 1.3]

**How it works:** Normalizes the commodity's taste score against the user's strongest commodity score, then applies up to +30% boost. A post in the user's most-interacted commodity gets 1.3×; a post in a commodity the user has never interacted with gets 1.0×.

**If `commodity_weights` is empty** (no commodity interactions yet): returns 1.0 — no effect.

### Factor 4: Engagement Multiplier

```python
saves = getattr(post, "save_count", 0)
raw_eng = saves * 3 + post.comment_count * 2 + post.like_count
engagement = min(math.log1p(raw_eng) / 6.9, 1.0)
# 6.9 ≈ log1p(1000) — normalizer: a post with ~1000 weighted engagement units scores 1.0
final_factor = (1 + engagement)
```

**Weight rationale:** saves have 3× weight, comments 2×, likes 1× — reflecting decreasing intent depth.

**Range of `engagement`:** [0, 1]
**Range of `(1 + engagement)`:** [1.0, 2.0]

**Examples:**
- New post (0 engagement): (1 + 0) = 1.0×
- Saves=5, comments=3, likes=20: raw=5×3+3×2+20=41 → log1p(41)/6.9 = 0.542 → 1.542×
- Saves=50, comments=20, likes=200: raw=390 → log1p(390)/6.9 = 0.860 → 1.860×

### Factor 5: Freshness Multiplier

See Part 7. Range: [1.0, 1.4].

### Factor 6: Social / Author Affinity (`social`)

```python
is_followed = author_user_id in followed_user_ids

if is_followed:
    social = 1.5
else:
    author_score = author_weights.get(str(post.profile_id), 0.0)
    social = taste_service.get_author_affinity(author_score)
```

**For followed authors:** Fixed 1.5× multiplier.

**For non-followed authors:**

```python
def get_author_affinity(decayed_net_score):
    # source: taste_service.py
    # AUTHOR_AFFINITY_MAX = 1.2
    # AUTHOR_AFFINITY_SATURATION = 20.0
    if decayed_net_score <= 0:
        return 1.0
    normalized = math.log1p(decayed_net_score) / math.log1p(AUTHOR_AFFINITY_SATURATION)
    return 1.0 + (AUTHOR_AFFINITY_MAX - 1.0) * min(normalized, 1.0)
```

Range: [1.0, 1.2] for non-followed authors.

**Examples:**
- Author never interacted with: score=0 → 1.0×
- One save on author's post (decayed net score ≈ 5.0): log1p(5)/log1p(20) = 1.792/3.045 = 0.589 → 1.0 + 0.2×0.589 = **1.118×**
- Author at saturation (score=20): 1.0 + 0.2×1.0 = **1.2×**

**`author_weights` population:** Author rows in `user_post_taste` are only written when `pos_delta >= AUTHOR_TASTE_MIN_DELTA (2.0)`. Eligible signals: like(3.0), save(5.0), comment(4.0), share(4.0), revisit(6.0), dwell_medium(2.0), dwell_long(3.5). Impression(0.1) and dwell_short(0.5) do not write author rows.

### Final Score Formula

```
final_score = vec_score
            × _category_weight(cat_weights, category)
            × _commodity_multiplier(commodity_weights, post.commodity_id)
            × (1 + engagement)
            × _freshness(post.created_at)
            × social
```

### Worked Example — Final Score Calculation

**Candidate Post A** (Deal/Req, Rice, 2h old, non-followed author):

```
vec_score = 0.87

category: deal_req → cat_weights["deal_req"] = 85.01
  _category_weight = log1p(85.01) / 14.514 = 4.454 / 14.514 = 0.307

commodity: Rice (commodity_id=1)
  commodity_weights = {"1": 12.0, "2": 3.0}  (user mostly trades rice)
  max_score = 12.0
  score = 12.0 → normalized = 12.0/12.0 = 1.0 → multiplier = 1.0 + 0.3×1.0 = 1.30

engagement: saves=5, comments=3, likes=20
  raw_eng = 15 + 6 + 20 = 41
  log1p(41) / 6.9 = 3.738 / 6.9 = 0.542
  (1 + 0.542) = 1.542

freshness: 2h old → 1.0 + 0.4 × exp(-2/8) = 1.0 + 0.4×0.779 = 1.312

social: not followed, author_score=8.0
  log1p(8.0)/log1p(20.0) = 2.197/3.045 = 0.721
  1.0 + 0.2×0.721 = 1.144

final_score = 0.87 × 0.307 × 1.30 × 1.542 × 1.312 × 1.144
            = 0.87 × 0.307 = 0.267
            × 1.30        = 0.347
            × 1.542       = 0.535
            × 1.312       = 0.702
            × 1.144       = 0.803
```

**Candidate Post B** (Knowledge, Rice, 48h old, followed author):

```
vec_score = 0.91   (slightly better ANN match)

category: knowledge → cat_weights["knowledge"] = 17.01
  _category_weight = log1p(17.01) / 14.514 = 2.888 / 14.514 = 0.199

commodity: Rice → same 1.30

engagement: saves=20, comments=8, likes=60
  raw_eng = 60 + 16 + 60 = 136
  log1p(136) / 6.9 = 4.921 / 6.9 = 0.713
  (1 + 0.713) = 1.713

freshness: 48h → 1.0 + 0.4 × exp(-48/8) = 1.0 + 0.4×0.002 = 1.001

social: followed author → 1.5

final_score = 0.91 × 0.199 × 1.30 × 1.713 × 1.001 × 1.5
            = 0.91 × 0.199 = 0.181
            × 1.30        = 0.235
            × 1.713       = 0.403
            × 1.001       = 0.403
            × 1.5         = 0.605
```

**Result: Post A (0.803) outranks Post B (0.605)** despite Post B having a higher vec_score and more engagement, because:
1. Post A is in deal_req (weight 0.307 vs 0.199) — category taste matters most
2. Post A is 2h old (freshness 1.312 vs 1.001) — 31% freshness advantage
3. Post B's followed-author boost (1.5×) is overcome by Post A's freshness + category advantage

---

## Part 9 — Diversity Filtering

### `_apply_diversity()`

Source: `post_recommendation_module/service.py`

```python
def _apply_diversity(scored, limit=FEED_SIZE):
    # FEED_SIZE = 25, MAX_PER_CATEGORY = 8, MAX_PER_AUTHOR = 3
    cat_counts: dict[str, int] = {}
    author_counts: dict[int, int] = {}
    result = []

    for item in scored:     # scored is already sorted descending by final_score
        cat = item["category"]
        author = item["author_profile_id"]
        if cat_counts.get(cat, 0) >= MAX_PER_CATEGORY:
            continue        # skip: category cap reached
        if author_counts.get(author, 0) >= MAX_PER_AUTHOR:
            continue        # skip: author cap reached
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
        author_counts[author] = author_counts.get(author, 0) + 1
        result.append(item)
        if len(result) >= limit:
            break

    return result
```

**Constants (source: constants.py):**
- `FEED_SIZE = 25` — target feed size (also passed as `limit` from the router)
- `MAX_PER_CATEGORY = 8` — at most 8 posts from any single category
- `MAX_PER_AUTHOR = 3` — at most 3 posts from any single author

**Processing order:** Iterates the already-scored and sorted list. Higher-scoring posts are accepted first; lower-scoring posts from the same author/category are rejected.

**Example:**

Input (sorted by final_score, 10 candidates):

| # | post_id | category | author | final_score |
|---|---------|----------|--------|-------------|
| 1 | 101 | deal_req | 5 | 0.803 |
| 2 | 204 | deal_req | 8 | 0.761 |
| 3 | 155 | market_update | 5 | 0.734 |
| 4 | 302 | deal_req | 5 | 0.712 | ← author 5 would be their 2nd post |
| 5 | 401 | knowledge | 11 | 0.698 |
| 6 | 503 | deal_req | 12 | 0.687 |
| 7 | 210 | discussion | 5 | 0.655 | ← author 5 would be their 3rd post |
| 8 | 305 | deal_req | 5 | 0.621 | ← author 5's 4th post — REJECTED |
| 9 | 108 | knowledge | 11 | 0.598 |
| 10 | 412 | discussion | 7 | 0.571 |

Output (limit=10 for this example, MAX_PER_AUTHOR=3):
Posts 1–7 accepted. Post 8 rejected (author 5 already has 3 posts: 101, 302, 210). Post 9 accepted. Post 10 accepted.

**Implication:** A very prolific author whose posts all score highly will have only 3 in the feed. This prevents any single author from monopolizing the feed.

---

## Part 10 — Seen Post Exclusion

### Schema

See `seen_posts` table in Part 2. Key fields: `profile_id`, `post_id`, `seen_at`. Unique constraint on `(profile_id, post_id)`.

### How posts become seen

**Path 1: Dwell event ≥ 3000 ms (batch endpoint)**

Source: `post_user_interaction/service.py`, `process_interaction_batch()`

```python
if (event.event_type == "dwell"
    and value_ms is not None
    and value_ms >= DWELL_SEEN_MS):   # DWELL_SEEN_MS = 3000
    seen_post_ids.append(event.post_id)

# After all events processed:
if seen_post_ids:
    db.execute(text("""
        INSERT INTO seen_posts (profile_id, post_id, seen_at)
        SELECT :profile_id, unnest(CAST(:post_ids AS int[])), :seen_at
        ON CONFLICT (profile_id, post_id) DO NOTHING
    """), {...})
```

**Path 2: Post detail open**

Source: `post_recommendation_module/service.py`, `record_seen()`

```python
def record_seen(db, profile_id, post_ids):
    now = datetime.now(timezone.utc)
    for pid in post_ids:
        db.add(SeenPost(profile_id=profile_id, post_id=pid, seen_at=now))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
```

Called from `post/service.py` → `get_post()` after a successful post detail retrieval.

### How exclusion works

Source: `post_recommendation_module/service.py`, `_seen_post_ids()`

```python
def _seen_post_ids(db, profile_id):
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    rows = db.query(SeenPost.post_id).filter(
        SeenPost.profile_id == profile_id,
        SeenPost.seen_at >= cutoff
    ).all()
    return {r[0] for r in rows}
```

This set is used as `pool_exclude`, which is passed to every ANN query and popular-post query as an exclusion list.

### Time window

30-day exclusion. A post seen on day 0 is excluded until day 30. After 30 days it becomes eligible again and may reappear in the feed.

### Infinite scroll behavior

The seen-post exclusion set is the sole pagination cursor. There is no offset, page number, or delivery token.

```
Feed call 1 → exclusion set = {}        → returns posts A, B, C...Y
User dwells ≥ 3s on posts A, B, C      → seen_posts INSERT
Feed call 2 → exclusion set = {A,B,C}  → returns posts Z, AA, BB... (A/B/C excluded)
```

If the user closes and reopens the app without sending dwell events, the next feed call returns the same posts (exclusion set unchanged).

**`has_more` flag:** Set to `len(posts) >= limit`. If the reranker + diversity filter produced fewer posts than requested, the pool is exhausted for the current exclusion set.

---

## Part 11 — API Documentation

### Router 1: Post CRUD (`/posts`)

Prefix: `/posts`, file: `app/modules/post/router.py`

#### `POST /posts/upload-image?content_type=...`
- **Auth:** Required
- **Purpose:** Get a signed S3 upload URL for a post image
- **Service call:** `service.get_post_upload_url(profile_id, content_type)`
- **Response:** `{upload_url, image_url, content_type}`
- **Errors:** `400` unsupported content_type

#### `POST /posts/`
- **Auth:** Required
- **Body:** `PostCreate`
- **Service call:** `service.create_post(db, profile_id, payload)`
- **Side effects:** Verifies image URLs exist in storage; inserts `Post`; inserts `PostDealDetails` if category=4; calls `rec_service.index_post()` to create `post_embeddings` row
- **Response:** `201 PostResponse`

#### `GET /posts/mine?limit=20&offset=0`
- **Auth:** Required
- **Service call:** `service.get_my_posts()`
- **Response:** `PostResponse[]`

#### `GET /posts/following?limit=20&offset=0`
- **Auth:** Required
- **Service call:** `service.get_following_feed()` — last 7 days from followed profiles
- **Response:** `PostResponse[]`

#### `GET /posts/saved?limit=20&offset=0`
- **Auth:** Required
- **Service call:** `service.get_saved_posts()`
- **Response:** `PostResponse[]`

#### `GET /posts/{post_id}`
- **Auth:** Required
- **Service call:** `service.get_post()`
- **Side effects:** `_record_view()` — inserts `post_views` (unique), increments `view_count`; on duplicate triggers revisit event and taste update; `record_seen()` — inserts `seen_posts`
- **Response:** `PostResponse`
- **Errors:** `404`

#### `PATCH /posts/{post_id}`
- **Auth:** Required (owner only)
- **Body:** `PostUpdate` (all fields optional)
- **Errors:** `403`, `404`

#### `DELETE /posts/{post_id}`
- **Auth:** Required (owner only)
- **Side effects:** Calls `rec_service.remove_post_index()` → sets `post_embeddings.is_active = False`; cascades to all interaction tables
- **Response:** `204`

#### `POST /posts/{post_id}/like`
- **Auth:** Required
- **Side effects on like:** INSERT `post_likes`; `posts.like_count` +1; `record_interaction("like")` → taste update
- **Side effects on unlike:** DELETE `post_likes`; `posts.like_count` -1; no taste update
- **Response:** `{liked: bool, like_count: int}`

#### `GET /posts/{post_id}/comments?limit=20&offset=0`
- **Auth:** Required
- **Response:** `CommentResponse[]`

#### `POST /posts/{post_id}/comments`
- **Auth:** Required
- **Body:** `{content: string}`
- **Side effects:** INSERT `post_comments`; `posts.comment_count` +1; `record_interaction("comment")` → taste update
- **Response:** `201 CommentResponse`
- **Errors:** `403` comments disabled

#### `DELETE /posts/{post_id}/comments/{comment_id}`
- **Auth:** Required (comment author only)
- **Side effects:** DELETE `post_comments`; `posts.comment_count` -1
- **Response:** `204`

#### `POST /posts/{post_id}/share`
- **Auth:** Required
- **Side effects:** INSERT `post_shares`; `posts.share_count` +1; `record_interaction("share")` → taste update
- **Response:** `{share_count: int}`

#### `POST /posts/{post_id}/save`
- **Auth:** Required
- **Side effects on save:** INSERT `post_saves`; `posts.save_count` +1; `record_interaction("save")` → taste update
- **Side effects on unsave:** DELETE `post_saves`; `posts.save_count` -1; no taste update
- **Response:** `{saved: bool}`

#### `POST /posts/{post_id}/close`
- **Auth:** Required (owner of Deal post only)
- **Side effects on close:** `rec_service.remove_post_index()` — removes from feed
- **Side effects on reopen:** `rec_service.index_post()` — re-inserts into feed
- **Response:** `{is_closed: bool}`

---

### Router 2: Recommendation (`/posts/recommendation`)

Prefix: `/posts/recommendation`, file: `post_recommendation_module/router.py`

#### `GET /posts/recommendation/feed?limit=25`
- **Auth:** Required
- **Query params:** `limit` (int, default 25, range 1–50)
- **Service call:** `service.get_recommended_posts(db, profile_id, limit)`
- **Response:** `FeedResponse {posts: FeedPostCard[], has_more: bool}`
- **Errors:** `404` profile not found

#### `POST /posts/recommendation/seen` *(deprecated no-op)*
- **Auth:** Required
- **Body:** `{post_ids: [int]}`
- **Response:** `204`
- **Note:** Does nothing. Retained for backward compatibility with older clients.

#### `POST /posts/recommendation/jobs/expiry`
- **Auth:** None (internal trigger)
- **Service call:** `jobs.run_expiry_job(db)`
- **Response:** `{status: "ok", details: {soft_expired, migrated_to_warm, migrated_to_cold, hard_deleted}}`

#### `POST /posts/recommendation/jobs/popular-sync`
- **Auth:** None (internal trigger)
- **Service call:** `jobs.run_popular_posts_sync(db)`
- **Response:** `{status: "ok", details: {synced, top_ids_count}}`

---

### Router 3: Interaction (`/posts/interactions`)

Prefix: `/posts/interactions`, file: `post_user_interaction/router.py`

#### `POST /posts/interactions/batch`
- **Auth:** Required
- **Body:** `InteractionBatchPayload {events: [InteractionEventItem], max 200}`
- **Service call:** `interaction_service.process_interaction_batch(db, profile_id, payload.events)`
- **Side effects:** Bulk inserts `post_interaction_events`; inserts `seen_posts` for dwell ≥ 3000ms
- **Response:** `InteractionBatchResult {accepted: int, dropped: int}`
- **Errors:** `422` invalid event_type, missing value_ms on dwell, empty/oversized batch

#### `POST /posts/interactions/jobs/taste-update`
- **Auth:** None (internal trigger)
- **Service call:** `interaction_jobs.run_taste_update_job(db)`
- **Response:** `{status: "ok", details: {processed, taste_updates}}`

#### `POST /posts/interactions/jobs/ignore-detect`
- **Auth:** None (internal trigger)
- **Service call:** `interaction_jobs.run_ignore_detection_job(db)`
- **Response:** `{status: "ok", details: {pairs_detected, taste_updates}}`

---

## Part 12 — Scheduler Documentation

Source: `app/core/scheduler.py`

The scheduler is `APScheduler.BackgroundScheduler(timezone="Asia/Kolkata")`, started in `main.py`'s `lifespan` context manager.

### Job 1: `posts.expiry`

| Attribute | Value |
|-----------|-------|
| Frequency | Every 1 hour |
| Entry point | `_run_expiry_job()` → `run_expiry_job(db)` |
| Source | `post_recommendation_module/jobs.py` |

**Logic:**

1. **Soft-expire:** Query `post_embeddings WHERE is_active=True AND expires_at <= now`. Set `is_active = False`. Also delete matching rows from `popular_posts`.

2. **Hot → Warm transition:** Query `post_embeddings WHERE partition='hot' AND is_active=True AND created_at <= now - 72h AND category IN ('deal_req','knowledge','discussion')`. Set `partition = 'warm'`. Note: `market_update` is absent — it does not transition to warm, it is soft-expired at its 2-day `expires_at`.

3. **Warm → Cold transition:** Query `post_embeddings WHERE partition='warm' AND is_active=True AND created_at <= now - 120h AND category IN ('knowledge','discussion')`. Set `partition = 'cold'`. Note: `deal_req` is absent — it does not transition to cold.

4. **Hard-delete cold:** `DELETE FROM post_embeddings WHERE partition='cold' AND created_at <= now - 720h`.

**Tables touched:** `post_embeddings` (read + update + delete), `popular_posts` (delete)

**Recommendation impact:** Posts removed from `post_embeddings` never appear in the feed. The partition system ensures only relevant-age posts compete in the hot ANN scan.

---

### Job 2: `posts.popular`

| Attribute | Value |
|-----------|-------|
| Frequency | Every 15 minutes |
| Entry point | `_run_popular_sync()` → `run_popular_posts_sync(db)` |
| Source | `post_recommendation_module/jobs.py` |

**Logic:**

1. Get all active `post_ids` from `post_embeddings`.
2. Query `posts WHERE created_at >= now - 30 days AND id IN (active_post_ids)`.
3. For each post, compute velocity score:
   ```python
   velocity = (saves×3 + comments×2 + likes) / ((hours + 1) ** 1.5)
   ```
4. Sort descending. For each commodity index (0, 1, 2), take top 50 posts.
5. Delete all rows from `popular_posts`. Bulk insert new rows.

**Tables touched:** `post_embeddings` (read), `posts` (read), `popular_posts` (delete + insert)

**Velocity formula:** `(save_count×3 + comment_count×2 + like_count) / (hours_since_post + 1)^1.5`

The `(hours + 1)^1.5` denominator ages down the score super-linearly — a post with 100 engagement units at 10h scores much higher than the same post at 100h. The +1 prevents division by zero for brand-new posts.

---

### Job 3: `posts.taste_update`

| Attribute | Value |
|-----------|-------|
| Frequency | Every 15 minutes |
| Entry point | `_run_taste_update()` → `run_taste_update_job(db)` |
| Source | `post_user_interaction/jobs.py` |

**Logic:**

1. Query up to `_BATCH_SIZE = 500` unprocessed dwell events (FIFO by `id`):
   ```sql
   SELECT * FROM post_interaction_events
   WHERE event_type = 'dwell' AND processed_at IS NULL
   ORDER BY id LIMIT 500
   ```

2. Bulk-fetch `(post_id → (category_id, commodity_id, author_profile_id))` for all referenced posts.

3. For each event, classify via `derive_signal("dwell", value_ms)`:
   - **Bounce (< 2000ms):** `neg_delta = 0.5`. Accumulate into `upt_deltas` for category and commodity. Skip legacy write.
   - **Positive dwell (≥ 2000ms):** `pos_delta` per dwell bucket. Write to legacy `user_taste_profiles` (integer delta). Accumulate into `upt_deltas` for category, commodity. If `pos_delta >= AUTHOR_TASTE_MIN_DELTA (2.0)` and author ≠ viewer: accumulate author.

4. Apply legacy deltas: UPDATE `user_taste_profiles` for each profile.

5. Apply `user_post_taste` deltas via `taste_service.update_taste()` for each accumulated (profile, dim_type, dim_key).

6. Mark all 500 events `processed_at = now`.

7. Commit.

**Tables touched:** `post_interaction_events` (read + update `processed_at`), `post_embeddings` (via `Post` query for metadata), `user_taste_profiles` (update), `user_post_taste` (upsert)

---

### Job 4: `posts.ignore_detect`

| Attribute | Value |
|-----------|-------|
| Frequency | Daily at 03:00 IST |
| Entry point | `_run_ignore_detection()` → `run_ignore_detection_job(db)` |
| Source | `post_user_interaction/jobs.py` |

**Logic:**

1. Find repeated-ignore pairs via SQL aggregate:
   ```sql
   SELECT profile_id, post_id
   FROM post_interaction_events
   GROUP BY profile_id, post_id
   HAVING
       SUM(CASE WHEN event_type = 'impression' THEN 1 ELSE 0 END) >= 5
     AND SUM(CASE WHEN event_type IN ('dwell','open_read_more','open_carousel',
                                       'open_comments','revisit') THEN 1 ELSE 0 END) = 0
     AND SUM(CASE WHEN event_type = 'impression'
                       AND processed_at IS NULL THEN 1 ELSE 0 END) > 0
   ORDER BY profile_id, post_id
   LIMIT 500
   ```
   `REPEATED_IGNORE_THRESHOLD = 5`, `_IGNORE_BATCH_SIZE = 500`

2. For each pair: apply `IGNORE_NEG_DELTA = 1.0` negative to `user_post_taste` category and commodity.

3. Mark impression events for detected pairs as `processed_at = now` via raw UPDATE:
   ```sql
   UPDATE post_interaction_events
   SET processed_at = :now
   WHERE event_type = 'impression'
     AND processed_at IS NULL
     AND (profile_id, post_id) IN (...)
   ```
   This ensures each pair is only actioned once — the HAVING clause requires at least one unprocessed impression to trigger detection.

**Tables touched:** `post_interaction_events` (aggregate read + update), `posts` (read category/commodity), `user_post_taste` (upsert negative)

---

## Part 13 — End-to-End Example

### Setup

**User: Ramesh (profile_id=7, role_id=1 Trader)**
- Commodities: Rice (id=1)
- Location: Surat (lat=21.17, lon=72.83)
- Quantity range: 50–200 MT
- `user_post_taste`: empty (new user)
- `user_taste_profiles`: does not exist yet
- `seen_posts`: empty

### Step 1: Initial Feed Request

`GET /posts/recommendation/feed`

**Profile load:** role_id=1, commodities=[1 (Rice)], quantity_min=50, quantity_max=200

**Vector:** `post_feed_vector` not set → compute `build_user_feed_vector()`:
```
commodity: [0, 1/1, 0] = [0, 1.0, 0]   (Rice → index 1)
role:      [1, 0, 0]                     (Trader → index 0)
geo: cos(21.17°)×cos(72.83°) = 0.932×0.295 = 0.275
     cos(21.17°)×sin(72.83°) = 0.932×0.957 = 0.892
     sin(21.17°)              = 0.361
qty: min(125/5000, 1.0) = 0.025
user_vec = [0, 1.0, 0, 1, 0, 0, 0.275, 0.892, 0.361, 0.025]
```

**Taste weights:**
- category: cold-start → Trader defaults: `{deal_req:100, market_update:80, discussion:20, knowledge:20}`
- commodity: {} (empty)
- author: {} (empty)

**ANN retrieval (hot):** Fetches top-150 posts from hot partition ordered by cosine distance to user_vec.

Assume pool has 90 candidates after hot scan (> MIN_POOL_SIZE=80, so warm/cold skipped).

**Popular posts:** Top 30 velocity posts for commodity_idx=1 (Rice) appended. Pool grows to ~100 candidates.

**Fresh injection:** 2 Rice posts published in last 4h injected with their exact vec_scores.

**Rerank:** Each of ~102 candidates scored. New user with empty taste:
- category weights fall back to Trader defaults via confidence blend
- commodity multiplier = 1.0 for all (no commodity taste yet)
- author multiplier = 1.0 for all (no author taste yet)
- social: depends on follows

**Diversity filter:** Applied with MAX_PER_CATEGORY=8, MAX_PER_AUTHOR=3. Returns top 25.

**Response:** `FeedResponse {posts: [...25 FeedPostCards...], has_more: true}`

---

### Step 2: User Views Post #101 (Deal/Req, Rice, author profile_id=22)

`GET /posts/101`

**DB state before:**
- `post_views`: no row for (101, 7)
- `posts.view_count` for 101: 42
- `user_taste_profiles` for profile 7: does not exist
- `user_post_taste` for profile 7: empty

**`_record_view(db, 101, 7)`:**
- INSERT INTO post_views (post_id=101, profile_id=7) → **success** (first view)
- UPDATE posts SET view_count=43 WHERE id=101

**`rec_service.record_seen(db, 7, [101])`:**
- INSERT INTO seen_posts (profile_id=7, post_id=101, seen_at=now)

**DB state after:**
- `post_views`: row (101, 7) exists
- `posts.view_count` for 101: 43
- `seen_posts`: row (7, 101)
- No taste change — view alone does not update taste (only revisit does, on second open)

---

### Step 3: User Scrolls Feed — Sends Batch Events

`POST /posts/interactions/batch`

```json
{
  "events": [
    {"post_id": 101, "event_type": "impression",      "occurred_at": "2026-06-08T10:20:00Z"},
    {"post_id": 101, "event_type": "dwell",            "value_ms": 12400, "occurred_at": "2026-06-08T10:20:12Z"},
    {"post_id": 203, "event_type": "impression",      "occurred_at": "2026-06-08T10:20:15Z"},
    {"post_id": 203, "event_type": "dwell",            "value_ms": 900,   "occurred_at": "2026-06-08T10:20:16Z"},
    {"post_id": 305, "event_type": "open_read_more",  "occurred_at": "2026-06-08T10:20:40Z"}
  ]
}
```

**`process_interaction_batch()`:**
- All 5 events are within 2 hours → accepted
- All post_ids exist → accepted
- Post 101 dwell: value_ms=12400, capped at 300000 → stored as 12400
- Post 203 dwell: value_ms=900 → stored as 900

Bulk INSERT 5 rows into `post_interaction_events`.

Post 101 dwell (12400 ≥ DWELL_SEEN_MS=3000):
- INSERT INTO seen_posts (7, 101) ON CONFLICT DO NOTHING → ignored (already seen from GET)

Response: `{accepted: 5, dropped: 0}`

**Later — `run_taste_update_job()` fires (within 15 min):**

Fetches unprocessed dwell events for profile 7:
- event for post 101: value_ms=12400 → `classify_dwell(12400)` → "dwell_long" (≥30000? No → 8000-30000 → "dwell_medium") → +2.0 positive

Wait, 12400 is between 8000 and 30000 → "dwell_medium" → pos_delta=2.0

Post 101: category=deal_req (category_id=4), commodity_id=1, author_profile_id=22

Accumulations:
```
upt_deltas[(7, "category", "deal_req")]  += [2.0, 0.0, 1]
upt_deltas[(7, "commodity", "1")]        += [2.0, 0.0, 1]
# pos_delta=2.0 >= AUTHOR_TASTE_MIN_DELTA=2.0 AND author(22) != viewer(7)
upt_deltas[(7, "author", "22")]          += [2.0, 0.0, 1]
```

- event for post 203: value_ms=900 → "dwell_bounce" → neg_delta=0.5
Post 203: assume category=market_update, commodity_id=1

```
# bounce — only negative, no legacy write, no author
upt_deltas[(7, "category", "market_update")] += [0.0, 0.5, 1]
upt_deltas[(7, "commodity", "1")]            += [0.0, 0.5, 1]
```

Legacy write for dwell_medium (+2.0 → int_delta=2):
- `user_taste_profiles` row does not exist → create with Trader defaults:
  ```
  market_update_count=80, deal_req_count=100, discussion_count=20, knowledge_count=20, total_events=0
  ```
- `deal_req_count += 2` → 102
- `total_events += 1` → 1

Apply `user_post_taste` upserts:

**DB state after taste_update_job:**

`user_post_taste`:

| profile_id | dimension_type | dimension_key | positive_score | negative_score | event_count |
|------------|---------------|---------------|----------------|----------------|-------------|
| 7 | category | deal_req | 2.0 | 0.0 | 1 |
| 7 | category | market_update | 0.0 | 0.5 | 1 |
| 7 | commodity | 1 | 2.0 | 0.5 | 2 |
| 7 | author | 22 | 2.0 | 0.0 | 1 |

`user_taste_profiles`:

| profile_id | market_update_count | deal_req_count | discussion_count | knowledge_count | total_events |
|------------|--------------------|-----------------|-----------------|--------------------|-------------|
| 7 | 80 | 102 | 20 | 20 | 1 |

---

### Step 4: User Likes Post #101

`POST /posts/101/like`

`toggle_like(db, 101, 7)`:
- No existing `post_likes` row → like path
- INSERT INTO post_likes (101, 7)
- UPDATE posts SET like_count = like_count + 1 WHERE id=101
- `record_interaction(db, 7, category_id=4, "like", commodity_id=1, author_profile_id=22)`
  - `derive_signal("like", None)` → (3.0, 0.0)
  - `_to_int_delta(3.0)` → 3
  - `user_taste_profiles` for profile 7 exists now → `deal_req_count += 3` → 105; `total_events += 1` → 2
  - `UPSERT user_post_taste (7, "category", "deal_req", +3.0, 0.0)` → positive_score=5.0, event_count=2
  - `UPSERT user_post_taste (7, "commodity", "1", +3.0, 0.0)` → positive_score=5.0, negative_score=0.5, event_count=3
  - `UPSERT user_post_taste (7, "author", "22", +3.0, 0.0)` → positive_score=5.0, event_count=2

**DB state after like:**

`user_post_taste`:

| dimension_type | dimension_key | positive_score | negative_score | event_count |
|---------------|---------------|----------------|----------------|-------------|
| category | deal_req | 5.0 | 0.0 | 2 |
| category | market_update | 0.0 | 0.5 | 1 |
| commodity | 1 | 5.0 | 0.5 | 3 |
| author | 22 | 5.0 | 0.0 | 2 |

---

### Step 5: Second Feed Request

`GET /posts/recommendation/feed`

**Taste weights now (`total_events = 2` across both tables, but `user_post_taste.event_count` is per-row — `get_taste_weights` counts total_events as sum of event_count across returned rows):**

For category (total_events = 2 + 1 = 3, rows: deal_req and market_update):
- deal_req: decayed positive = 5.0, net = 5.0 - 0 = 5.0
- market_update: decayed positive = 0.0, net = 0.0 - (0.5×0.6) = -0.3 → floor at 0.05

Confidence = 3/20 = 0.15, blend with Trader defaults:
- deal_req:      0.15×5.0  + 0.85×100 = 0.75  + 85.0  = 85.75
- market_update: 0.15×0.05 + 0.85×80  = 0.0075 + 68.0 = 68.01  (learned score floored at 0.05)
- discussion:    0.15×0.05 + 0.85×20  = 0.0075 + 17.0 = 17.01
- knowledge:     0.15×0.05 + 0.85×20  = 0.0075 + 17.0 = 17.01

Commodity weights: `{"1": max(5.0-(0.5×0.6), 0.05)} = {"1": 4.7}`
→ `_commodity_multiplier({"1": 4.7}, commodity_id=1)` = 1.0 + 0.3×(4.7/4.7) = **1.3×** for Rice posts

Author weights: `{"22": 5.0}`
→ `get_author_affinity(5.0)` = 1.0 + 0.2 × (log1p(5.0)/log1p(20.0)) = 1.0 + 0.2×0.589 = **1.118×** for posts by author 22

**Seen posts:** post 101 excluded (seen in step 2/3)

**Why future recommendations change:**
- Deal/Req posts will rank higher (cat_weight for deal_req is 85.75 vs 68.01 for market_update)
- Rice posts get a 1.3× commodity multiplier
- Posts by author 22 get a 1.118× affinity boost
- Market_update posts are slightly downranked (small negative score from the bounce)
- Post 101 does not appear (in seen_posts)

---

## Part 14 — Architecture Summary

### Complete Recommendation Flow

```
┌──────────────────────────────────────────────────────────────────────┐
│                     GET /posts/recommendation/feed                    │
└─────────────────────────────┬────────────────────────────────────────┘
                              │
              ┌───────────────▼───────────────┐
              │         Load Profile           │
              │  Profile, Business, Commodity  │
              └───────────────┬───────────────┘
                              │
              ┌───────────────▼───────────────┐
              │       Resolve User Vector      │
              │  UserEmbedding.post_feed_vector│
              │  OR build_user_feed_vector()   │
              └───────────────┬───────────────┘
                              │
              ┌───────────────▼───────────────┐
              │       Load Taste Weights       │
              │  get_taste_weights(category)   │
              │  get_taste_weights(commodity)  │
              │  get_taste_weights(author)     │
              └───────────────┬───────────────┘
                              │
              ┌───────────────▼───────────────┐
              │     Load Exclusion Sets        │
              │  seen_posts (30-day window)    │
              │  followed_user_ids             │
              └───────────────┬───────────────┘
                              │
              ┌───────────────▼───────────────┐
              │      Candidate Retrieval       │
              │  ANN hot (≤72h, max 150)       │
              │  → if pool<80: ANN warm        │
              │  → if pool<80: ANN cold        │
              │  + popular_posts (top 30)      │
              │  + fresh (<4h, max 5)          │
              └───────────────┬───────────────┘
                              │
              ┌───────────────▼───────────────┐
              │           Rerank               │
              │  vec × category × commodity   │
              │  × engagement × freshness     │
              │  × social/author_affinity     │
              └───────────────┬───────────────┘
                              │
              ┌───────────────▼───────────────┐
              │       Diversity Filter         │
              │  MAX_PER_CATEGORY=8            │
              │  MAX_PER_AUTHOR=3              │
              │  FEED_SIZE=25                  │
              └───────────────┬───────────────┘
                              │
              ┌───────────────▼───────────────┐
              │       Build Feed Cards         │
              │  Posts + Authors + Likes +     │
              │  Saves + Comment previews      │
              └───────────────┬───────────────┘
                              │
                     FeedResponse[]
```

---

### Complete Interaction Flow

```
User Action
    │
    ├─ Open post (GET /posts/{id})
    │     ├─ post_views INSERT (unique)
    │     │     ├─ [first view] view_count +1
    │     │     └─ [duplicate] record_revisit_event()
    │     │               └─ post_interaction_events INSERT (revisit)
    │     │               └─ record_interaction("revisit") → taste update
    │     └─ seen_posts INSERT
    │
    ├─ Like   → post_likes + like_count   + record_interaction("like",  +3.0)
    ├─ Save   → post_saves + save_count   + record_interaction("save",  +5.0)
    ├─ Share  → post_shares + share_count + record_interaction("share", +4.0)
    └─ Comment→ post_comments + comment_count + record_interaction("comment", +4.0)
                    │
                    └─ record_interaction() writes:
                          1. user_taste_profiles (category col += int_delta, total_events +1)
                          2. user_post_taste category (pos += delta)
                          3. user_post_taste commodity (pos += delta)
                          4. user_post_taste author (pos += delta, if eligible)

Batch events (POST /posts/interactions/batch)
    │
    ├─ INSERT post_interaction_events (bulk)
    └─ seen_posts INSERT for dwell ≥ 3000ms

Scheduled jobs:
    ├─ posts.taste_update (15min) reads post_interaction_events (dwell, unprocessed)
    │     ├─ bounce (<2000ms) → user_post_taste negative
    │     ├─ positive dwell  → user_taste_profiles + user_post_taste
    │     └─ marks processed_at
    └─ posts.ignore_detect (daily) finds 5+ impressions + 0 engagement
          └─ user_post_taste negative (category + commodity)
```

---

### Complete Taste-Building Flow

```
Signal Source          Signal Type         Dimensions Updated
─────────────────      ────────────────    ──────────────────────────────────
Like (+3.0)            Synchronous         category, commodity, author (if ≥2.0)
Save (+5.0)            Synchronous         category, commodity, author
Share (+4.0)           Synchronous         category, commodity, author
Comment (+4.0)         Synchronous         category, commodity, author
Revisit (+6.0)         Synchronous         category, commodity, author

Dwell medium (+2.0)    Async (15min job)   category, commodity, author (if ≥2.0)
Dwell long (+3.5)      Async (15min job)   category, commodity, author
Dwell short (+0.5)     Async (15min job)   category, commodity
Bounce (−0.5)          Async (15min job)   category, commodity (negative only)

Repeated ignore (−1.0) Async (daily job)   category, commodity (negative only)

                             │
                             ▼
                    user_post_taste
                    (composite PK: profile_id, dimension_type, dimension_key)
                    positive_score | negative_score | event_count | last_event_at

                             │
                             ▼ at feed request time
                    get_taste_weights(category)
                      1. Exponential decay: pos × exp(-0.023 × days_since)
                      2. Net = decayed_pos - (neg × 0.6), floor 0.05
                      3. Confidence blend (category only):
                         score = confidence×learned + (1-confidence)×role_default
                         confidence = min(total_events / 20, 1.0)

                             │
                             ▼ in _rerank()
                    _category_weight(): log1p normalized → [0,1]
                    _commodity_multiplier(): normalized → [1.0, 1.3]
                    get_author_affinity(): log1p compressed → [1.0, 1.2]
```

---

### Table Dependency Graph

```
users ──────────────────────────────────────────────────────────┐
  └─ profile ──────────────────────────────────────────────────┤
       ├─ business (geo coordinates)                           │
       ├─ profile_commodities                                  │
       ├─ user_embeddings (post_feed_vector)                   │
       │                                                        │
       └─ [writes to]                                           │
            ├─ posts ──────────────────────────────────────────┤
            │    ├─ post_embeddings                             │
            │    ├─ popular_posts                              │
            │    ├─ post_views                                  │
            │    ├─ post_likes                                  │
            │    ├─ post_saves                                  │
            │    ├─ post_comments                              │
            │    ├─ post_shares                                 │
            │    └─ post_deal_details                           │
            │                                                    │
            ├─ seen_posts                                        │
            ├─ post_interaction_events                          │
            ├─ user_post_taste                                   │
            └─ user_taste_profiles                              │
                                                                 │
user_connections ───────────────────────────────────────────────┘
                    (read during rerank for social boost)
```

---

### Service Dependency Graph

```
post/router.py
    └─ post/service.py
            ├─ rec_service  (post_recommendation_module/service.py)
            │       ├─ taste_service (post_user_interaction/taste_service.py)
            │       └─ vector (post_recommendation_module/vector.py)
            └─ interaction_service (post_user_interaction/service.py)
                    └─ taste_service (post_user_interaction/taste_service.py)

post_recommendation_module/router.py
    └─ post_recommendation_module/service.py
            └─ taste_service

post_user_interaction/router.py
    ├─ post_user_interaction/service.py
    └─ post_user_interaction/jobs.py
            └─ taste_service

scheduler.py
    ├─ post_recommendation_module/jobs.py
    └─ post_user_interaction/jobs.py
            └─ taste_service
```

---

## Constants Reference

All constants are sourced from their origin files. No values are assumed.

### `post_recommendation_module/constants.py`

| Constant | Value | Purpose |
|----------|-------|---------|
| `CATEGORY_NAMES` | `{1:"market_update", 2:"knowledge", 3:"discussion", 4:"deal_req"}` | ID→name mapping |
| `COMMODITY_ID_TO_IDX` | `{1:1, 2:0, 3:2}` | Rice→1, Cotton→0, Sugar→2 |
| `ROLE_ID_TO_IDX` | `{1:0, 2:2, 3:1}` | Trader→0, Exporter→1, Broker→2 |
| `CATEGORY_EXPIRY_DAYS` | `{market_update:2, deal_req:7, discussion:14, knowledge:90}` | Post lifetime in index |
| `HOT_MAX_HOURS` | 72 | Partition boundary: hot→warm |
| `WARM_MAX_HOURS` | 120 | Partition boundary: warm→cold |
| `COLD_MAX_HOURS` | 720 | Hard delete boundary |
| `VECTOR_DIM` | 10 | Post/user vector dimensionality |
| `FEED_WEIGHTS` | `[3,3,3, 2,2,2, 1.5,1.5,1.5, 1.0]` | Weighted cosine dimension weights |
| `QTY_SCALE_MT` | 5000.0 | Quantity normalizer |
| `MIN_POOL_SIZE` | 80 | Threshold to skip next partition |
| `FETCH_TARGET` | 150 | Max ANN candidates per partition |
| `FEED_SIZE` | 25 | Default feed size |
| `POPULAR_LIMIT` | 30 | Max popular posts per feed |
| `MAX_PER_CATEGORY` | 8 | Diversity cap per category |
| `MAX_PER_AUTHOR` | 3 | Diversity cap per author |
| `FRESH_BOOST_PEAK` | 0.4 | Freshness multiplier peak |
| `FRESH_DECAY_TAU` | 8.0 | Freshness decay time constant (hours) |
| `FRESH_INJECT_HOURS` | 4 | Age threshold for fresh injection |
| `FRESH_SLOTS` | 5 | Max fresh posts injected per call |

### `post_user_interaction/constants.py`

| Constant | Value | Purpose |
|----------|-------|---------|
| `DEFAULT_TASTE` | Per role, see Part 4 | Cold-start category seeds |
| `TASTE_BOOTSTRAP_EVENTS` | 20 | Interactions before learned taste dominates |
| `VALID_CLIENT_EVENT_TYPES` | frozenset of 6 types | Accepted batch event types |
| `MAX_EVENT_AGE_HOURS` | 2 | Stale event cutoff |
| `DWELL_SEEN_MS` | 3000 | Dwell threshold for seen-post marking |
| `DWELL_BOUNCE_MS` | 2000 | Below = bounce (negative signal) |
| `DWELL_SHORT_MS` | 8000 | 2000–8000 = short dwell |
| `DWELL_LONG_MS` | 30000 | ≥30000 = long dwell |
| `DWELL_VALUE_CAP_MS` | 300000 | Server-enforced max dwell value |
| `SIGNAL_WEIGHTS` | See signal table in Part 8 | (pos_delta, neg_delta) per event |
| `TASTE_DECAY_LAMBDA` | 0.023 | Exponential decay rate (~30-day half-life) |
| `AUTHOR_TASTE_MIN_DELTA` | 2.0 | Min signal strength to write author row |
| `AUTHOR_AFFINITY_MAX` | 1.2 | Max author affinity multiplier |
| `AUTHOR_AFFINITY_SATURATION` | 20.0 | Score at which max multiplier is reached |
| `REPEATED_IGNORE_THRESHOLD` | 5 | Impressions without engagement to trigger ignore |
| `IGNORE_NEG_DELTA` | 1.0 | Negative delta applied per ignored pair |

### `post_user_interaction/taste_service.py` (module-level)

| Constant | Value | Purpose |
|----------|-------|---------|
| `_SCORE_FLOOR` | 0.05 | Minimum net score for any taste dimension |
| `_NEG_DISCOUNT` | 0.6 | Negative score discount factor |
