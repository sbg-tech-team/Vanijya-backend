# Post vs News — Module Parity Audit
_Generated: 2026-06-24 | Codebase: Vanijya Backend_

---

## Phase 1: Post Module — Reference Implementation

### 1.1 API Endpoints

All endpoints require authentication via `get_current_profile_id` (JWT dependency) unless noted.

**Post CRUD** (`app/modules/post/router.py`, prefix `/posts`)

| Method | Path | Auth | Query Params | Request Body | Response Schema |
|---|---|---|---|---|---|
| POST | `/posts/upload-image` | profile_id | `content_type: str` | — | `{upload_url, image_url, content_type}` |
| POST | `/posts/` | profile_id | — | `PostCreate` | `PostResponse` |
| GET | `/posts/mine` | profile_id | `limit=20`, `cursor: int\|None` | — | `MyPostFeedResponse` |
| GET | `/posts/following` | profile_id | `limit=20`, `cursor: int\|None` | — | `FollowingFeedResponse` |
| GET | `/posts/saved` | profile_id | `limit=20`, `cursor: int\|None` | — | `SavedPostFeedResponse` |
| GET | `/posts/{post_id}` | profile_id | — | — | `PostResponse` |
| PATCH | `/posts/{post_id}` | profile_id | — | `PostUpdate` | `PostResponse` |
| DELETE | `/posts/{post_id}` | profile_id | — | — | 204 |
| POST | `/posts/{post_id}/like` | profile_id | — | — | `LikeResponse` |
| GET | `/posts/{post_id}/comments` | profile_id | `limit=20`, `cursor: int\|None` | — | `CommentFeedResponse` |
| POST | `/posts/{post_id}/comments` | profile_id | — | `CommentCreate` | `CommentResponse` |
| DELETE | `/posts/{post_id}/comments/{comment_id}` | profile_id | — | — | 204 |
| GET | `/posts/{post_id}/share` | user_id | — | — | chat share recipients |
| POST | `/posts/{post_id}/send` | profile_id + user_id | — | `PostSendRequest` | `PostSendResponse` |
| POST | `/posts/{post_id}/record-share` | profile_id | — | — | `ShareResponse` |
| POST | `/posts/{post_id}/save` | profile_id | — | — | `SaveResponse` |
| POST | `/posts/{post_id}/close` | profile_id | — | — | `DealClosedResponse` |

**Post Recommendation** (`app/modules/post/post_recommendation_module/router.py`, prefix `/posts/recommendation`)

| Method | Path | Auth | Query Params | Response Schema |
|---|---|---|---|---|
| GET | `/posts/recommendation/feed` | profile_id | `limit: int` (1–50, default 25) | `FeedResponse` |
| POST | `/posts/recommendation/seen` | profile_id | — | 204 (no-op shim) |
| POST | `/posts/recommendation/jobs/expiry` | none | — | `JobResult` |
| POST | `/posts/recommendation/jobs/popular-sync` | none | — | `JobResult` |

**Post Interactions** (`app/modules/post/post_user_interaction/router.py`, prefix `/posts/interactions`)

| Method | Path | Auth | Request Body | Response Schema |
|---|---|---|---|---|
| POST | `/posts/interactions/batch` | profile_id | `InteractionBatchPayload` | `InteractionBatchResult` |
| POST | `/posts/interactions/jobs/taste-update` | none | — | `JobResult` |
| POST | `/posts/interactions/jobs/ignore-detect` | none | — | `JobResult` |

---

### 1.2 Data Models

**`posts`** — `app/modules/post/models.py:Post`
- `id: Integer PK autoincrement`
- `profile_id: Integer FK(profile.id, CASCADE)`
- `category_id: Integer FK(post_categories.id)` — 1=Market Update, 2=Knowledge, 3=Discussion, 4=Deal/Requirement
- `commodity_id: Integer FK(commodities.id)`
- `title: String(200)`
- `image_urls: ARRAY(String) nullable`
- `caption: Text`
- `source_url: String(500) nullable`
- `latitude, longitude: Float nullable`
- `location_name: String(200) nullable`
- `is_public: Boolean default=True`
- `target_roles: ARRAY(Integer) nullable`
- `allow_comments: Boolean default=True`
- `like_count, view_count, comment_count, share_count, save_count: Integer default=0`
- `created_at: DateTime`

**`post_deal_details`** — `app/modules/post/models.py:PostDealDetails`
- `id: Integer PK`; `post_id: Integer FK(posts.id, CASCADE) UNIQUE`
- `grain_type: String(100)`, `grain_size: String(50)`
- `commodity_quantity: Float`, `quantity_unit: String(20)` — MT | quintal
- `commodity_price: Float`, `price_type: String(20)` — fixed | negotiable
- `is_closed: Boolean default=False`

**`post_views`** — `app/modules/post/models.py:PostView`
- `id, post_id FK(posts.id CASCADE), profile_id FK(profile.id CASCADE)`
- `viewed_at: DateTime`
- UNIQUE(`post_id`, `profile_id`) — duplicate view fires revisit event

**`post_likes`** — UNIQUE(`post_id`, `profile_id`)

**`post_comments`** — `content: Text`, `created_at: DateTime`

**`post_shares`** — `shared_at: DateTime`

**`post_saves`** — UNIQUE(`post_id`, `profile_id`)

**`post_categories`** — Fixed seed (1=Market Update, 2=Knowledge, 3=Discussion, 4=Deal/Req)

**`post_embeddings`** — `app/modules/post/post_recommendation_module/models.py:PostEmbedding`
- `post_id FK(posts.id CASCADE) PK`
- `vector: Vector(10)` (pgvector)
- `partition: String(10)` — hot | warm | cold
- `is_active: Boolean`
- `expires_at: DateTime(tz)`
- `category: String(30)`
- `commodity_idx: Integer` — 0=cotton, 1=rice, 2=sugar
- `created_at: DateTime(tz)`

**`popular_posts`** — `app/modules/post/post_recommendation_module/models.py:PopularPost`
- `id PK`, `post_id FK UNIQUE`, `commodity_idx: Integer INDEX`
- `category: String(30)`, `velocity_score: Float`
- `saves_count, likes_count, comments_count: Integer`
- `hours_since_post: Float`, `last_updated_at: DateTime(tz)`
- `is_active: Boolean`

**`seen_posts`** — `app/modules/post/post_recommendation_module/models.py:SeenPost`
- `id PK`, `profile_id FK`, `post_id FK`
- `seen_at: DateTime(tz)`
- UNIQUE(`profile_id`, `post_id`)

**`post_interaction_events`** — `app/modules/post/post_user_interaction/models.py:PostInteractionEvent`
- `id PK autoincrement`
- `profile_id FK`, `post_id FK`
- `event_type: String(30)` — impression | dwell | open_read_more | open_carousel | open_comments | link_click | revisit
- `value_ms: Integer nullable` — dwell only
- `occurred_at: DateTime(tz)`, `created_at: DateTime(tz)`
- `processed_at: DateTime(tz) nullable` — NULL = unprocessed
- Indexes: `(profile_id, post_id)`, `(event_type, created_at)`, `(created_at)`, `(event_type, processed_at)`

**`user_post_taste`** — `app/modules/post/post_user_interaction/models.py:UserPostTaste`
- Composite PK: `(profile_id, dimension_type, dimension_key)`
- `dimension_type: String(20)` — category | commodity | author
- `dimension_key: String(50)` — category slug | commodity_id str | author profile_id str
- `positive_score, negative_score: Float`, `event_count: Integer`
- `last_event_at: DateTime(tz)`
- Index: `(profile_id, dimension_type)`

**`user_taste_profiles`** — `app/modules/post/post_user_interaction/models.py:UserTasteProfile` (legacy)
- `profile_id FK PK`
- `market_update_count, deal_req_count, discussion_count, knowledge_count: Integer`
- `total_events: Integer`, `updated_at: DateTime(tz)`

---

### 1.3 Business Rules

**PostCreate validation** (`app/modules/post/schemas.py`)
- `title` and `caption` must not be empty or whitespace-only
- `image_urls` max 5 entries
- `price_type` must be `fixed` or `negotiable`
- `quantity_unit` must be `MT` or `quintal`
- `deal_details` is **required** when `category_id == 4` (Deal/Requirement)
- Image URLs validated against the `posts` storage bucket — profile_id must match the URL path prefix; object existence verified with retry (0.15s + 0.35s)

**PostUpdate validation** (`app/modules/post/schemas.py:PostUpdate`)
- All fields optional (PATCH semantics)
- Same empty-string validations as PostCreate

**Post ownership** (`app/modules/post/service.py`)
- `update_post` and `delete_post` raise `PostForbiddenError` if `post.profile_id != caller_profile_id`
- `toggle_deal_closed` similarly enforces ownership and requires `category_id == 4`

**Comment rules** (`app/modules/post/service.py`)
- Cannot add comment if `post.allow_comments == False` → `CommentsDisabledError`
- Only comment owner can delete their comment

**View deduplication** (`app/modules/post/service.py:_record_view`)
- UNIQUE constraint on `(post_id, profile_id)` in `post_views`
- Duplicate view → `IntegrityError` → rollback → `record_revisit_event()`; `view_count` NOT incremented on revisit

**Share** (`app/modules/post/service.py:send_post`)
- In-app share checks DM `ConvStatus.ACTIVE` and group `chat_perm` + member role + freeze status
- Partial delivery: silently skips failing recipients; `share_count` incremented exactly once
- External share: only increments counter, no chat delivery

**Interaction recording** (`app/modules/post/service.py`)
- `like`, `save`, `comment`, `share` all call `interaction_service.record_interaction()` synchronously
- Failures are caught and suppressed (never break the primary operation)

**Deal close** (`app/modules/post/service.py:toggle_deal_closed`)
- On close: calls `rec_service.remove_post_index()` (soft-deactivates embedding)
- On reopen: calls `rec_service.index_post()` (re-indexes with `partition=hot`)

**Post visibility on feed** (`app/modules/post/service.py:get_following_feed`)
- Only posts from `_active_profile_ids()` (all profiles in DB) are served
- Posts older than 30 days excluded from following feed
- Seen posts (shared with recommendation feed) excluded

**Interaction batch** (`app/modules/post/post_user_interaction/service.py:process_interaction_batch`)
- Events older than `MAX_EVENT_AGE_HOURS` (2h) are silently dropped
- Events referencing non-existent `post_id` are dropped
- `dwell` requires `value_ms`; capped at `DWELL_VALUE_CAP_MS` (300,000ms = 5 min)
- Max 200 events per batch
- Dwell >= 3,000ms → upsert into `seen_posts`

---

### 1.4 Recommendation Flow

```
User → GET /posts/recommendation/feed
     → post_recommendation_module/router.py:get_feed()
     → service.get_recommended_posts(db, profile_id)
         ↓
         1. Load Profile + commodities + business (for user vector)
         2. Load UserEmbedding.post_feed_vector (or build via build_user_feed_vector)
         3. Load taste weights: category, commodity, author via taste_service.get_taste_weights()
         4. Load followed_user_ids via UserConnection query
         5. Load seen_ids (last 30 days) from seen_posts
         ↓
         6. ANN pre-filter: _query_partition("hot", FETCH_TARGET=150, pool_exclude, user_vec)
            → pgvector HNSW <=> cosine distance on post_embeddings
            → For each result: compute weighted_cosine_similarity (exact, reranking)
         ↓
         7. If pool < MIN_POOL_SIZE (80): repeat for "warm" partition
         8. If pool < MIN_POOL_SIZE: repeat for "cold" partition
         ↓
         9. Append popular posts: _get_popular_posts() from popular_posts table (up to 30)
        10. Fresh inject: _ensure_fresh_in_pool() — posts < 4h old not yet in ANN results
        ↓
        11. _rerank(pool, cat_weights, commodity_weights, author_weights, followed_user_ids)
            → For each candidate: fetch Post + Profile
            → Compute: vec_score × category_weight × commodity_multiplier × (1+engagement) × freshness × social
        ↓
        12. _apply_diversity(scored, limit=FEED_SIZE=25)
            → MAX_PER_CATEGORY=8, MAX_PER_AUTHOR=3
        ↓
        13. _build_feed_cards() → batch-load Post, Profile+business, PostLike, PostSave
     → Return FeedResponse{posts, has_more}
```

---

### 1.5 Cursor Pagination & Infinite Scroll

**Recommendation feed** (`/posts/recommendation/feed`): No cursor. Returns up to `FEED_SIZE` (25) posts, `has_more = len(posts) >= limit`. Client calls again for next page (seen deduplication prevents re-serving).

**My posts** (`/posts/mine`): Integer cursor = last `post_id` on current page. Next query: `Post.id < cursor_post_id`, ordered by `Post.id DESC`. `next_cursor = posts[-1].id` if `len(posts) == limit` else `None`.

**Saved posts** (`/posts/saved`): Integer cursor = last `PostSave.id`. Next query: `PostSave.id < cursor_save_id`. `next_cursor = saves[-1].id` if `len(saves) == limit` else `None`.

**Following feed** (`/posts/following`): Integer cursor = last `post_id` in scored list. Cursor is used to find position in the *already-sorted* scored list (`ranked_ids.index(cursor_post_id) + 1`). If cursor post is no longer present (seen/removed), restarts from top. `next_cursor = page_posts[-1].id` if `len(page_posts) == limit` else `None`.

**Comments** (`/posts/{id}/comments`): Integer cursor = last `comment_id`. Next query: `PostComment.id > cursor_comment_id` (ascending, chronological), ordered by `PostComment.id ASC`.

All implementations use the same convention: `next_cursor = None` means end of feed (confidence: High).

---

### 1.6 User Interaction Types

**Client-submitted via `/posts/interactions/batch`** (`app/modules/post/post_user_interaction/constants.py`):
- `impression` — card shown in feed; pos_delta=0.1
- `dwell` — time spent on card (requires `value_ms`); classified into bounce/short/medium/long
- `open_read_more` — user expanded caption; pos_delta=1.5
- `open_carousel` — user swiped images; pos_delta=1.0
- `open_comments` — user opened comments; pos_delta=1.5
- `link_click` — user tapped source URL; pos_delta=2.0

**Synchronous (explicit) — via dedicated endpoints:**
- `like` — toggle; pos_delta=3.0; writes to `post_likes`
- `save` — toggle; pos_delta=5.0; writes to `post_saves`
- `comment` — creates comment; pos_delta=4.0
- `share` — records share; pos_delta=4.0

**Server-generated (not accepted from client):**
- `revisit` — fired when `post_views` UNIQUE constraint triggers (duplicate view); pos_delta=6.0

**Dwell classification** (`app/modules/post/post_user_interaction/service.py:classify_dwell`):
- `< 2,000ms` → `dwell_bounce` (neg_delta=0.5)
- `2,000–8,000ms` → `dwell_short` (pos_delta=0.5)
- `8,000–30,000ms` → `dwell_medium` (pos_delta=2.0)
- `>= 30,000ms` → `dwell_long` (pos_delta=3.5)
- `>= 3,000ms` → also marks post as `seen`

---

### 1.7 Taste Update Flow

**Synchronous (like / save / comment / share / revisit)** — `record_interaction()` in `app/modules/post/post_user_interaction/service.py`:
1. Compute `(pos_delta, neg_delta)` via `derive_signal(signal_type, None)`
2. Look up or create `UserTasteProfile` (legacy table), seed from role defaults if new
3. Increment the appropriate category column (e.g., `deal_req_count += round(pos_delta)`)
4. Call `taste_service.update_taste(db, profile_id, "category", category, pos_delta, neg_delta)` → upsert `user_post_taste`
5. If `commodity_id` provided: `update_taste(..., "commodity", str(commodity_id), ...)`
6. If `author_profile_id` provided AND author != viewer AND `pos_delta >= 2.0`: `update_taste(..., "author", str(author_profile_id), ...)`
7. Single `db.commit()` — taste and interaction commit atomically

**Asynchronous (dwell / open_* / link_click)** — `run_taste_update_job()` in `app/modules/post/post_user_interaction/jobs.py`:
- Runs every 15 min; processes batches of 500 unprocessed passive events
- Positive dwell: writes to both `user_taste_profiles` (legacy) and `user_post_taste` (category, commodity, author)
- Bounce dwell: writes negative delta to `user_post_taste` only (no negative column on legacy table)
- Marks `processed_at = now` for all fetched events

**Ignore detection** — `run_ignore_detection_job()` in `app/modules/post/post_user_interaction/jobs.py`:
- Runs daily; finds `(profile_id, post_id)` pairs with `>=5` impressions and zero engagement
- Applies `IGNORE_NEG_DELTA=1.0` to category and commodity in `user_post_taste`
- Marks impression events as processed so each pair is actioned exactly once

**Redis keys written**: None by Post interaction system itself. The `taste/session_taste` infrastructure writes Redis, but Post's own taste write path is purely PostgreSQL.

---

### 1.8 Background Jobs

**`run_expiry_job(db)`** — `app/modules/post/post_recommendation_module/jobs.py`
- Triggered via: `POST /posts/recommendation/jobs/expiry` (no auth); intended for scheduler
- Reads `PostEmbedding` where `is_active=True AND expires_at <= now` → sets `is_active=False`
- Also deletes from `popular_posts` for expired post_ids
- Migrates hot → warm: embeddings older than 72h in hot partition, category in `{deal_req, knowledge, discussion}` → `partition=warm`
- Migrates warm → cold: embeddings older than 120h in warm, category in `{knowledge, discussion}` → `partition=cold`
- Hard-deletes cold embeddings older than 720h

**`run_popular_posts_sync(db)`** — `app/modules/post/post_recommendation_module/jobs.py`
- Triggered via: `POST /posts/recommendation/jobs/popular-sync`; intended for every 15 min
- Fetches all Posts created in last 30 days that have an active embedding
- Computes velocity: `(saves×3 + comments×2 + likes) / (hours+1)^1.5`
- Selects top 50 per commodity_idx bucket
- Deletes all rows from `popular_posts` and bulk-inserts new rows

**`run_taste_update_job(db)`** — `app/modules/post/post_user_interaction/jobs.py`
- Triggered via: `POST /posts/interactions/jobs/taste-update`; intended for every 15 min
- Processes up to 500 unprocessed passive events (dwell, open_*, link_click)
- Writes category, commodity, author taste to `user_post_taste` + legacy `user_taste_profiles`

**`run_ignore_detection_job(db)`** — `app/modules/post/post_user_interaction/jobs.py`
- Triggered via: `POST /posts/interactions/jobs/ignore-detect`; intended daily
- Finds and penalises `(profile, post)` pairs with repeated ignoring

---

### 1.9 Redis Usage

The Post module itself does **not** write any Redis keys directly. The shared `taste/session_taste` infrastructure uses Redis for session taste. The Post recommendation system reads/writes PostgreSQL only.

The feed-level session taste file (`app/modules/feed/session_taste.py`) uses a separate Redis key pattern `session:{profile_id}:{session_id}` with GET/SET and 2h TTL, but this is the home-feed mixer layer, not Post-specific.

Confidence: High — no `redis` import found in any `post/` module file.

---

### 1.10 Recommendation Layers

**Layer 1: ANN hot/warm/cold partition search** (`service.py:_query_partition`)
- Uses pgvector `<=>` cosine distance operator on `post_embeddings` table
- Three partitions: hot (0–72h), warm (72–120h), cold (120–720h)
- Fills candidate pool up to `FETCH_TARGET=150` per partition; stops early if `MIN_POOL_SIZE=80` reached

**Layer 2: Platform-wide popular** (`service.py:_get_popular_posts`)
- Reads `popular_posts` table (updated every 15 min by `run_popular_posts_sync`)
- Filters by user's commodity indices, ordered by `velocity_score DESC`, limit 30
- Vec_score = 0.5 (flat; no ANN match)

**Layer 3: Fresh inject** (`service.py:_ensure_fresh_in_pool`)
- Posts published in last 4h that were not in the ANN results
- Computes actual `weighted_cosine_similarity` for these posts
- Caps at `FRESH_SLOTS=5` slots

**Reranking formula** (`service.py:_rerank`):
```
final_score = vec_score × category_weight × commodity_multiplier × (1 + engagement) × freshness × social
```
Where:
- `category_weight = log1p(cat_weights[category]) / sum(log1p(v) for v in cat_weights.values())`
- `commodity_multiplier = 1.0 + 0.3 × min(commodity_score / max_score, 1.0)`
- `engagement = min(log1p(saves×3 + comments×2 + likes) / 6.9, 1.0)`
- `freshness = 1.0 + 0.4 × exp(-age_hours / 8.0)` (peak ~1.4 at publish, decays to ~1.0 at 48h)
- `social = 1.5` if followed author, else `get_author_affinity(author_score)` (1.0–1.2)

---

### 1.11 Affinity Calculations

**Category affinity** (`app/modules/post/post_user_interaction/taste_service.py:get_taste_weights`):
- Reads `user_post_taste` rows where `dimension_type='category'`
- Per row: `decayed = positive_score × exp(-0.023 × days_since_last_event)`
- `net = decayed - (negative_score × 0.6)`
- Floor at `_SCORE_FLOOR = 0.05`
- Cold start: if `total_events < 20`, confidence-blend with role defaults: `confidence = total_events/20`, `score = confidence × learned + (1-confidence) × default`
- Category weights in reranker: normalised via `log1p` before use

**Commodity affinity** (`taste_service.get_taste_weights`, `dimension_type='commodity'`):
- Same decay/net formula; no confidence blend (empty dict returned for cold start)
- Used in `_commodity_multiplier()`: `1.0 + 0.3 × min(score/max_score, 1.0)`

**Author/profile affinity** (`taste_service.get_author_affinity`):
- Reads `user_post_taste` where `dimension_type='author'`, `dimension_key=str(author_profile_id)`
- `get_author_affinity(score) = 1.0 + (0.2) × min(log1p(score)/log1p(20), 1.0)`
- Range: 1.0 (no interactions) to 1.2 (saturation at score=20)
- Only written for signals with `pos_delta >= 2.0` (like, save, comment, share, revisit, dwell_medium, dwell_long, link_click)

**Following boost** (`service.py:_rerank`): `social = 1.5` if `author.users_id in followed_user_ids`; bypasses author affinity lookup entirely.

**Geo affinity**: Embedded in the 10-dim vector (dims 6–8: 3D unit-sphere Cartesian). Computed at index time from author's business location or post-level lat/lon override. Compared via weighted cosine similarity with FEED_WEIGHTS (geo weight = 1.5 per dim).

---

### 1.12 Seen/Dedup Mechanism

**Primary store**: `seen_posts` table (`app/modules/post/post_recommendation_module/models.py:SeenPost`)
- Written when: (a) dwell >= 3,000ms in batch endpoint; (b) user opens a post (`get_post()` calls `rec_service.record_seen()`)
- `record_seen()` uses `ON CONFLICT (profile_id, post_id) DO NOTHING` via raw SQL upsert
- Seen-window: 30 days — `_seen_post_ids()` filters `seen_at >= now - 30 days`
- All three feed types (recommendation, following, saved) use the same `seen_posts` table

**Following feed** (`app/modules/post/service.py:get_following_feed`):
- Loads full `seen_ids` set and applies `Post.id.notin_(seen_ids)` filter before scoring

**Recommendation feed** (`app/modules/post/post_recommendation_module/service.py`):
- Starts `pool_exclude = set(seen_ids)` and passes to `_query_partition(exclude_ids=pool_exclude)`
- Also excludes already-fetched candidates when querying subsequent partitions

---

### 1.13 Cold Start Handling

**New user with no interactions:**
1. `UserTasteProfile` doesn't exist → `get_taste_for_feed()` returns `DEFAULT_TASTE[role_id]` (role-seeded counts: Trader prefers deal_req+market_update; Broker prefers deal_req+price events; Exporter prefers market_update+deal_req)
2. `user_post_taste` has no rows → `get_taste_weights()` returns role defaults for category, empty dict for commodity/author
3. User vector: if no `UserEmbedding.post_feed_vector`, builds `build_user_feed_vector()` from `Profile.commodities` + `role_id` + `business.latitude/longitude` + `(quantity_min+quantity_max)/2`
4. Recommendation still runs — ANN search finds semantically relevant posts via commodity+role matching; freshness boost helps recent posts surface

**Bootstrap threshold**: `TASTE_BOOTSTRAP_EVENTS = 20`. Below this, category taste is confidence-blended (linear interpolation between learned and defaults).

---

### 1.14 Caching Strategy

**`popular_posts` table** (PostgreSQL): Materialized view updated by `run_popular_posts_sync` every 15 min. Entire table is deleted and rebuilt atomically.

**`seen_posts` table** (PostgreSQL): Append-only, keyed by `(profile_id, post_id)`. De-facto cache of post IDs to exclude. 30-day rolling window.

**`post_embeddings` partition** (PostgreSQL): Partition transition is the index's own freshness management. Hot→warm→cold→delete.

**No Redis caching** in the Post module itself. No response caching layer exists.

---

### 1.15 Filtering Pipeline

**Recommendation feed** (`app/modules/post/post_recommendation_module/service.py:get_recommended_posts`):
1. Exclude seen posts (`seen_ids` set, 30-day window)
2. ANN pre-filter: `is_active=True` on `post_embeddings` (closed deals and deleted posts removed at index time)
3. Fresh inject: additionally filters `is_public=True` and checks `target_roles` against viewer's role
4. Post-ANN: `posts` table lookup may return None for race-deleted posts → silently skipped in `_rerank`
5. Diversity cap: `MAX_PER_CATEGORY=8`, `MAX_PER_AUTHOR=3`

**Following feed** (`app/modules/post/service.py:get_following_feed`):
1. Only posts from followed profiles
2. Last 30 days: `Post.created_at >= cutoff`
3. Exclude seen posts: `Post.id.notin_(seen_ids)`
4. Closed deals shown but ranked lower (`closed_penalty = 0.5`)

**General post fetch** (`service.py:_get_post_or_raise`): filters `Post.profile_id.in_(_active_profile_ids(db))` to exclude posts from deleted profiles.

---

## Phase 2: News Module — Current Implementation

### 2.1 API Endpoints

All endpoints require auth unless noted. Auth is `get_current_profile_id` for feed/interactions, `get_current_user_id` for admin.

**News Feed** (`app/modules/news_new/feed/router.py`, prefix `/news`)

| Method | Path | Auth | Query Params | Response Schema |
|---|---|---|---|---|
| GET | `/news/feed` | profile_id | `limit` (1–50, default 20), `cursor: str\|None` | `FeedPage` |
| GET | `/news/feed/saved` | profile_id | `limit`, `cursor` | `FeedPage` |
| GET | `/news/feed/global` | profile_id | `limit`, `cursor` | `FeedPage` |
| GET | `/news/feed/domestic` | profile_id | `limit`, `cursor` | `FeedPage` |
| GET | `/news/feed/government` | profile_id | `limit`, `cursor` | `FeedPage` |
| GET | `/news/articles/{article_id}` | profile_id | — | `NewsCardDetail` |

**News Interactions** (`app/modules/news_new/news_user_interaction/router.py`, prefix `/news/interactions`)

| Method | Path | Auth | Request Body / Params | Response Schema |
|---|---|---|---|---|
| POST | `/news/interactions/batch` | profile_id | `NewsInteractionBatchPayload` | `{accepted, dropped}` |
| POST | `/news/interactions/like/{article_id}` | profile_id | — | `NewsLikeOut` |
| POST | `/news/interactions/save/{article_id}` | profile_id | — | `NewsSaveOut` |
| POST | `/news/interactions/share/{article_id}` | profile_id | `platform: str\|None` | `NewsShareOut` |
| GET | `/news/interactions/share-sheet/{article_id}` | user_id | — | share recipients |
| POST | `/news/interactions/send/{article_id}` | user_id + profile_id | `NewsSendRequest` | `NewsSendResponse` |

**News Admin** (`app/modules/news_new/ingestion/router.py`, prefix `/news/admin`)

| Method | Path | Auth | Query Params | Notes |
|---|---|---|---|---|
| POST | `/news/admin/ingest` | user_id | `query`, `country` | Trigger GNews fetch |
| POST | `/news/admin/enrich` | user_id | `limit` | Trigger Groq enrichment |
| GET | `/news/admin/stats` | user_id | — | Counts by status |

**News Recommendations** (`app/modules/news_new/news_recommendation_engine/router.py`, prefix `/news/recommendations`)
- Router is a stub with a comment only: `GET /news/recommendations/feed` is not implemented.

---

### 2.2 Data Models

**`news_raw_articles`** — `app/modules/news_new/ingestion/models.py:RawArticle`
- `id: UUID PK`
- `external_id: String(128) UNIQUE` — dedup key
- `title: String(500)`, `description: Text nullable`, `content: Text nullable`
- `article_url: String(1000)`, `image_url: String(1000) nullable`
- `published_at: DateTime` (UTC naive)
- `language: String(20)`, `source_name: String(200)`, `source_url: String(500)`, `source_country: String(80)`
- `authors: ARRAY(String)`, `is_duplicate: Boolean`
- `api_summary: Text nullable`, `raw_metadata: JSONB`
- `intelligence_status: String(20)` — pending | enriched | failed
- `platform_arrived_at: DateTime` — ingestion timestamp
- `is_active: Boolean` — soft delete (archived after 30 days)
- `created_at, updated_at: DateTime`
- Indexes: `intelligence_status`, `published_at`, `platform_arrived_at`

**`news_enriched_articles`** — `app/modules/news_new/intelligence/models.py:EnrichedArticle`
- `id: UUID PK`, `raw_article_id: UUID FK(news_raw_articles.id CASCADE) UNIQUE`
- `primary_factor: String(40)` — one of 10 slugs
- `factor_scores: JSONB` — `[{factor, score}]` top 1–3
- `geo_category: String(20)` — global | domestic
- `is_government: Boolean`
- `summary_bullets: JSONB`, `summary_long: Text nullable`
- `impact_direction: String(20)` — positive | neutral | negative
- `impact_score: Float` (0–10), `impact_factor: String(120)`, `impact_explanation: Text`
- `role_trader, role_broker, role_exporter: Float` — pre-computed from `RELEVANCY_MATRIX`
- `model_version: String(80)`, `generated_at: DateTime`, `created_at: DateTime`

**`news_interaction_events`** — `app/modules/news_new/news_user_interaction/models.py:NewsInteractionEvent`
- `id: Integer PK`, `profile_id FK`, `article_id UUID FK`
- `event_type: String(30)`, `value_ms: Integer nullable`, `occurred_at: DateTime`
- `created_at: DateTime`, `processed_at: DateTime nullable`
- Indexes: `(profile_id, article_id)`, `(event_type, created_at)`, `(created_at)`, `(event_type, processed_at)`

**`news_views`** — UNIQUE(`profile_id`, `article_id`)
- `id PK`, `profile_id FK`, `article_id UUID FK`
- `first_viewed_at: DateTime`, `last_viewed_at: DateTime`, `view_count: Integer`

**`news_likes`** — UNIQUE(`profile_id`, `article_id`)

**`news_saves`** — UNIQUE(`profile_id`, `article_id`)

**`news_shares`** — `platform: String(30) nullable`

**`news_article_stats`** — `app/modules/news_new/news_user_interaction/models.py:NewsArticleStats`
- `article_id UUID PK FK`
- `view_count, like_count, save_count, share_count: Integer`
- `updated_at: DateTime`

**`news_raw_trending`** — `app/modules/news_new/news_user_interaction/models.py:NewsTrending`
- `article_id UUID PK FK`, `velocity_score: Float`, `trending_rank: Integer nullable`
- `computed_at: DateTime`

**`user_news_taste`** — `app/modules/news_new/news_user_interaction/models.py:UserNewsTaste`
- Composite PK: `(profile_id, dimension_type, dimension_key)`
- `dimension_type: String(20)` — category | source | tag
- `dimension_key: String(80)`
- `positive_score, negative_score: Float`, `event_count: Integer`
- `last_event_at: DateTime`

**`user_news_taste_profiles`** — `app/modules/news_new/news_user_interaction/models.py:UserNewsTasteProfile`
- `profile_id PK FK`, `dominant_factor: String(40) nullable`
- `factor_weights: JSONB nullable`, `total_events: Integer`, `bootstrapped: Boolean`
- `updated_at: DateTime`

**`news_recommendation_scores`** — `app/modules/news_new/news_recommendation_engine/models.py:ArticleRecommendationScore`
- `id UUID PK`, UNIQUE(`profile_id`, `article_id`)
- `role_score, final_score: Float`, `profile_score, taste_score: Float nullable`
- `computed_at, model_version, is_served: ...`

**`news_feed_ranking_cache`** — UNIQUE(`profile_id`, `feed_type`)
- `ranked_article_ids: JSONB`, `computed_at, expires_at: DateTime`
- 2-hour TTL (`_CACHE_TTL_HOURS=2`)

---

### 2.3 Business Rules

**Feed** (`app/modules/news_new/feed/service.py`):
- Only enriched (`intelligence_status='enriched'`) AND active (`is_active=True`) articles served in main feed
- No personalisation filter by commodity or role in the main feed query — all enriched articles sorted by `platform_arrived_at DESC`
- Role score is computed and attached to each card from `EnrichedArticle.role_trader/broker/exporter` column, but NOT used for sorting/ranking

**Interaction batch** (`app/modules/news_new/news_user_interaction/service.py`):
- Events older than 2h dropped; max 200 per batch
- `dwell` requires `value_ms`; capped at `DWELL_VALUE_CAP_MS` (600,000ms = 10 min)
- `open_article` event triggers `upsert_view()` → revisit detection

**Like/Save** — toggle semantics: deletes if exists, creates if not. Counter adjusted in `news_article_stats`.

**Share** — `record_share()`: creates `NewsShare` row (not unique constraint), increments stats, writes taste.

**In-app share** (`send_article()`): same chat delivery logic as Post; increments `share_count` exactly once; `taste_from_article` called with `share_tap` signal (pos_delta=2.0).

**Dwell classification** (`service.py:classify_dwell`): Different thresholds from Post:
- `< 3,000ms` → `dwell_bounce`
- `3,000–15,000ms` → `dwell_short`
- `15,000–60,000ms` → `dwell_medium`
- `>= 60,000ms` → `dwell_long`
- `>= 5,000ms` → marks as "seen" (not implemented in batch — see gap in Phase 5)

**Taste write on explicit interactions** (`service.py:_taste_from_article`): Only writes `category` dimension (via `primary_factor`). Does NOT write commodity or author dimensions.

---

### 2.4 Recommendation Flow

```
User → GET /news/feed
     → feed/router.py:get_news_feed()
     → feed/service.py:get_trending_feed(db, profile_id, role_id, limit, cursor)
         ↓
         1. Query news_raw_articles WHERE is_active=True AND intelligence_status='enriched'
         2. ORDER BY platform_arrived_at DESC (pure reverse-chronological)
         3. Apply cursor (keyset pagination on platform_arrived_at + id)
         4. Batch-load EnrichedArticle, NewsArticleStats, NewsLike, NewsSave for page
         5. Compute role_score from enriched.role_trader/broker/exporter column
         6. Attach is_liked, is_saved, role_score, final_score(=role_score) to each card
     → Return FeedPage{items, cursor}
```

**No personalised recommendation feed is wired**. `GET /news/recommendations/feed` is stubbed — the `news_recommendation_engine` models and service exist but are NOT connected to any active feed endpoint.

**Role-based scoring** exists as a pre-computed column (`role_trader/broker/exporter`) populated at enrich time from `RELEVANCY_MATRIX`. It is attached to cards but does NOT influence sort order.

---

### 2.5 Cursor Pagination & Infinite Scroll

**All news feeds use keyset pagination** based on `(platform_arrived_at, id)`.

**Cursor encoding** (`app/modules/news_new/feed/service.py:encode_cursor`):
- `raw = f"{article.platform_arrived_at.isoformat()}|{article.id}"`
- Base64 URL-safe encoded
- Decoded to `(datetime, UUID)` tuple via `decode_cursor()`

**Feed query with cursor** (`get_trending_feed`):
```
WHERE (platform_arrived_at < ts) OR (platform_arrived_at = ts AND id < uid)
```
`has_more = len(articles) > limit` (over-fetches by 1); returns `next_cursor = encode_cursor(articles[-1])` if `has_more`, else `None`.

**Saved feed**: cursor applied to in-memory filtered list (no DB-level keyset; less efficient).

---

### 2.6 User Interaction Types

**Client-submitted via `/news/interactions/batch`** (`app/modules/news_new/news_user_interaction/constants.py`):
- `impression` — card shown; pos_delta=0.1
- `dwell` — time on card (requires `value_ms`); classified into bounce/short/medium/long
- `open_article` — user opened article detail; pos_delta=1.5; triggers view upsert + revisit check
- `share_tap` — user tapped share; pos_delta=2.0

**Synchronous (explicit):**
- `like` — toggle; pos_delta=3.0
- `save` — toggle; pos_delta=5.0
- `share` (external) — records share; taste uses `share_tap` signal (pos_delta=2.0)

**Server-generated:**
- `revisit` — fired by `upsert_view()` when `NewsView` already exists (second open_article)

**Notable absences vs Post**: `open_read_more`, `open_carousel`, `open_comments`, `link_click` are not defined for News. `comment` is not an interaction type (no commenting feature on News).

---

### 2.7 Taste Update Flow

**Synchronous (like / save / share / revisit)**:
- `_taste_from_article(db, profile_id, article_id, signal_type)` in `service.py`
- Looks up `EnrichedArticle.primary_factor` for the article
- Calls `taste_service.update_taste(db, profile_id, "category", factor, pos, neg)` — **category only**
- Does NOT write commodity or author dimensions

**Asynchronous**: No dwell taste-update job exists in News. The `NewsInteractionEvent` table has `processed_at` column mirroring Post's design, but `run_taste_update_job()` equivalent for News is **not implemented**.

**Trending job** (`app/modules/news_new/news_user_interaction/jobs.py:recalc_trending`):
- Runs every 5 min
- Reads `NewsInteractionEvent`, `NewsLike`, `NewsSave`, `NewsShare` from last 6h
- Computes velocity: `weighted_signal_sum / log1p(unique_profile_count)`
- Requires `TRENDING_MIN_UNIQUE_USERS=2` distinct profiles
- Upserts `NewsTrending` rows; removes articles no longer qualifying

**`taste_service.update_taste()`** (`app/modules/news_new/news_user_interaction/taste_service.py`):
- Atomic upsert into `user_news_taste`
- Applies 30-day exponential decay (`TASTE_DECAY_LAMBDA = ln(2)/30`)
- `get_taste_weights()` provides confidence-blended weights (role defaults until 20 events)

---

### 2.8 Background Jobs

**`recalc_trending(db)`** — `app/modules/news_new/news_user_interaction/jobs.py`
- Triggered: scheduler every 5 min
- Recomputes velocity from last `TRENDING_LOOKBACK_H=6` hours of interactions
- Upserts/deletes `NewsTrending` rows

**`run_news_pipeline()`** — `app/modules/news_new/ingestion/jobs.py`
- Triggered: scheduler every 30 min
- Step 1: `ingest_rotation(db, GNewsProvider())` — 2 queries from rotation pool per run
- Step 2: `enrich_pending(db, ENRICH_BATCH_LIMIT=20)` — enriches up to 20 pending articles
- Each step independently committed; GNews failure does not stop enrichment

**`archive_old_articles()`** — `app/modules/news_new/ingestion/jobs.py`
- Triggered: scheduler daily
- Sets `RawArticle.is_active=False` for articles where `published_at < now - 30 days`

---

### 2.9 Redis Usage

The News module itself does **not** write any Redis keys directly. The `news_feed_ranking_cache` table (PostgreSQL) provides a DB-level cache for ranked article IDs, but this is **not wired to any active endpoint** (only the models/service exist).

No Redis imports in any `news_new/` file. Confidence: High.

---

### 2.10 Recommendation Layers

**Currently active**: A single layer — reverse-chronological sort by `platform_arrived_at`.

**Scaffolded but not active**:
- `ArticleRecommendationScore` table — role_score column pre-populated via `compute_role_score()`
- `FeedRankingCache` table — 2h TTL keyset cache (models + service only; no endpoint reads it)
- `news_recommendation_engine/router.py` — stub only

**Role-based scoring** is attached to cards at response-assembly time but does NOT affect ordering.

---

### 2.11 Affinity Calculations

**Role relevance** (`app/modules/news_new/config.py:RELEVANCY_MATRIX`):
- Pre-computed at enrich time from a 10×3 matrix (factor slug → trader/broker/exporter weights, all 0–10 scale)
- Stored as `role_trader`, `role_broker`, `role_exporter` on `EnrichedArticle`
- Used only for display; does not rank the feed

**Category taste** (`app/modules/news_new/news_user_interaction/taste_service.py`):
- `user_news_taste` table with same decay formula as Post
- Cold-start: 20-event bootstrap, blends with `DEFAULT_TASTE` derived from `RELEVANCY_MATRIX`
- Read by `get_taste_weights()` — NOT yet called by any feed endpoint

**Source/tag affinity**: Defined in `TASTE_DIMENSIONS = frozenset({"category", "source", "tag"})` and `dimension_type` supports "source" and "tag" in `user_news_taste`, but no code writes source or tag taste rows. Not implemented.

**Commodity affinity**: Not implemented for News. No commodity dimension in `user_news_taste`.

**Author/source affinity**: Not implemented. No source-specific taste write exists (only category is written).

---

### 2.12 Seen/Dedup Mechanism

**`news_views` table** tracks per-user, per-article view history (UNIQUE constraint, `view_count` incremented on revisit).

**No "seen" exclusion from feed**: Unlike Post, the news feed does NOT exclude already-seen articles. The `news_views` table is used only for revisit detection and view counting. An article remains in the feed indefinitely after being seen.

**`NewsTrending` table**: Provides a separate trending snapshot, but trending is not used in the main feed (`get_trending_feed` is reverse-chronological, not trend-ordered despite the function name).

---

### 2.13 Cold Start Handling

**Feed cold start**: No personalisation for new users — everyone gets the same reverse-chronological feed. Role-score is attached but not used for ordering.

**Taste cold start** (`taste_service.get_taste_weights`): If no `user_news_taste` rows, returns `DEFAULT_TASTE[role_id]` derived from `RELEVANCY_MATRIX`. Below 20 events, confidence-blends with defaults. This taste is not yet connected to the feed.

---

### 2.14 Caching Strategy

**`news_article_stats`** (PostgreSQL): Per-article counter table. Updated on every like/save/share via `_adjust_stats()`. Read-path: batch-loaded in `_build_feed_page()`.

**`news_feed_ranking_cache`** (PostgreSQL, 2h TTL): Model and service exist (`app/modules/news_new/news_recommendation_engine/service.py:upsert_feed_ranking_cache`), but no active endpoint uses it.

No Redis caching. Confidence: High.

---

### 2.15 Filtering Pipeline

**`get_trending_feed`** (`app/modules/news_new/feed/service.py`):
1. `is_active=True` — excludes archived articles
2. `intelligence_status='enriched'` — excludes pending and failed articles
3. Keyset cursor pagination
4. No commodity, role, category, or seen-post filter

**`get_filtered_feed`** (for `/news/feed/global`, `/news/feed/domestic`, `/news/feed/government`):
1. First queries `EnrichedArticle` for matching `geo_category` or `is_government=True` → gets `filtered_ids`
2. Then queries `RawArticle` with `is_active=True AND id.in_(filtered_ids)`
3. Applies keyset cursor

**Saved feed**: No DB filter — loads all saved article_ids for the user, then fetches articles, then applies cursor in memory.

---

### 2.16 Ingestion Pipeline

**Sources**: GNews API only (`app/modules/news_new/ingestion/providers/gnews.py`). Provider-agnostic via `BaseNewsProvider` ABC.

**Rotation pool** (`app/modules/news_new/ingestion/news_queries.py`): 28 queries covering commodity lanes, policy/regulation, macro/geo, deal flow, and structural/local categories. Time-slot based rotation: slot = `unix_timestamp // 1800`, `start = (slot × per_run) % n`. Stateless — survives restarts.

**Per-run**: `GNEWS_QUERIES_PER_RUN=2` (2 queries × max 10 articles = 20 articles per run, 48 runs/day = ~96 requests/day — under free tier 100/day cap).

**Fetch** (`ingest_from_provider`):
1. `provider.fetch(query, country)` → list of raw provider items
2. Normalize via `provider.to_canonical()` → canonical dict
3. Dedup: `external_id` check against `seen` set (within-batch) and DB query (`_exists()`)
4. Missing `external_id` or `article_url` → skip
5. `db.add(RawArticle(..., intelligence_status='pending'))` for each new article
6. Single commit per ingest call

**Dedup strategy**: `external_id` UNIQUE constraint only. Title-similarity near-dedup is commented as deferred.

**Rate limiting**: `GNEWS_INTER_QUERY_DELAY_S=5.0` between queries. `GNEWS_FETCH_RETRIES=3` for 429 (back-off). 403 → `ProviderQuotaError` (stops remaining queries for the run).

---

### 2.17 Classification / Intelligence Pipeline

**`enrich_pending(db, limit, enricher)`** (`app/modules/news_new/intelligence/service.py`):
1. Fetches up to `ENRICH_BATCH_LIMIT=20` oldest `pending` articles (FIFO)
2. For each: `build_input_text()` — constructs `TITLE: ... DESCRIPTION: ... CONTENT: ...[capped at 1000 chars]`
3. Calls `GroqEnricher.enrich(text)` → Groq API (llama-3.1-8b-instant)
4. Validates response via `LLMEnrichment.model_validate()` — enforces enum constraints
5. Single retry on validation failure
6. On success: `role_relevance_for(primary_factor)` → looks up `RELEVANCY_MATRIX[primary_factor]` — **computed, never from LLM**
7. Creates `EnrichedArticle` row, sets raw article `intelligence_status='enriched'`
8. On failure: sets `intelligence_status='failed'`
9. Each article commits independently (crash-safe progress)

**Rate pacing**: `ENRICH_ARTICLES_PER_MIN=2.0` (RateLimiter: 30s/call). `GROQ_MAX_RETRIES=5`. 429 → exponential back-off via `retry-after` header.

**LLM output** (validated by `LLMEnrichment`):
- `primary_factor` (one of 10 slugs), `factor_scores` (1–3 entries), `geo_category` (global|domestic), `is_government` (bool), `summary_bullets` (list[str]), `impact.direction/score/factor/explanation`

---

## Phase 3: Feature Parity Matrix

| Capability | Post | News | Status | Notes |
|---|---|---|---|---|
| Feed generation | ✅ Recommendation + following | ✅ Reverse-chronological | 🟦 Intentional Difference | News is pull-based ingestion; ranking is less mature |
| Infinite scrolling | ✅ Integer cursor + seen-set exclusion | ✅ Keyset cursor | ✅ Both have infinite scroll | Different dedup strategies |
| Cursor pagination | ✅ Integer-keyed cursor | ✅ Base64 keyset (datetime+UUID) | ✅ Complete | News cursor is more robust |
| Filtering (geo/category) | ✅ category_id filter in following feed | ✅ geo/government filter endpoints | ✅ Complete | Post also filters by target_roles; News by geo_category/is_government |
| Sorting | ✅ Scored + ranked (composite score) | ⚠️ Reverse-chronological only | ⚠️ Partial | News role_score computed but not used in sort |
| Recommendation scoring | ✅ 10-dim vector + multi-factor reranker | ❌ Not wired | ❌ Missing | Scaffolding exists but no active personalised ranking endpoint |
| Category affinity | ✅ Full (UserPostTaste, decay, bootstrap) | ✅ UserNewsTaste exists | ⚠️ Partial | News taste not used by feed |
| Commodity affinity | ✅ Full (dimension_type=commodity) | ❌ Not implemented | ❌ Missing | No commodity dimension in user_news_taste |
| Entity affinity | ✅ (via factor/category) | ❌ Not implemented | ❌ Missing | News has factors but no per-entity taste |
| Source/author affinity | ✅ Author profile_id affinity | ❌ No source affinity written | ❌ Missing | user_news_taste supports 'source' dimension but nothing writes it |
| Session recommendation | ❌ Not implemented (taste/session_taste exists but Post doesn't wire it) | ❌ Not implemented | ❌ Missing | shared session_taste infra exists but not wired in either module |
| Global recommendation | ❌ Not implemented | ❌ Not implemented | ❌ Missing | user_global_taste infra exists but not wired |
| Recommendation updates | ✅ seen_posts + taste drive exclusion + reranking | ❌ No personalization-driven updates | ❌ Missing | |
| Interaction recording | ✅ Full: like, save, share, comment, view, dwell, impression | ✅ like, save, share, dwell, impression, open_article | ⚠️ Partial | News missing: comment, open_carousel, open_read_more, link_click |
| Click tracking | ✅ `open_read_more` = 1.5, `link_click` = 2.0 | ✅ `open_article` = 1.5 | ⚠️ Partial | Post has granular open events; News collapses all opens to `open_article` |
| Dwell time tracking | ✅ Full with `value_ms`, bounce/short/medium/long | ✅ Full with `value_ms`, different thresholds | ✅ Complete | Thresholds differ (news: longer; max cap 600s vs 300s) |
| Share | ✅ External + in-app (chat delivery) | ✅ External + in-app (chat delivery) | ✅ Complete | |
| Save/Bookmark | ✅ toggle; taste update; saved feed | ✅ toggle; taste update; saved feed | ✅ Complete | |
| Like | ✅ toggle; taste update; counter | ✅ toggle; taste update; counter | ✅ Complete | |
| Hide | ❌ Not implemented | ❌ Not implemented | ❌ Missing (both) | |
| Report | ❌ Not implemented | ❌ Not implemented | ❌ Missing (both) | |
| Not interested | ❌ Not implemented | ❌ Not implemented | ❌ Missing (both) | |
| Read/View tracking | ✅ post_views UNIQUE; revisit on conflict | ✅ news_views UNIQUE; revisit on conflict | ✅ Complete | |
| View counter | ✅ post.view_count incremented | ✅ news_article_stats.view_count (via stats table) | ⚠️ Partial | Post updates inline; News updates via stats table but view_count not updated in batch processing |
| Seen history | ✅ seen_posts table, 30-day window | ❌ No seen-exclusion from feed | ❌ Missing | news_views exists but not used for exclusion |
| Deduplication | ✅ seen_posts excludes from recommendation + following feeds | ❌ Not applied to news feeds | ❌ Missing | |
| Feed freshness | ✅ Freshness boost (0.4 decay constant, 8h half-life) | ⚠️ Reverse-chrono = fresh-first, no decay boost | ⚠️ Partial | Post has explicit freshness multiplier; News relies on publish order |
| Cold start | ✅ Role-seeded defaults, confidence blend | ✅ Role-seeded defaults from RELEVANCY_MATRIX | ✅ Complete | Taste cold start complete; feed cold start = everyone gets same chrono feed in News |
| Caching | ⚠️ popular_posts table (15-min) | ⚠️ news_feed_ranking_cache model exists but not wired | ⚠️ Partial | |
| Redis integration | ❌ No Redis in Post module | ❌ No Redis in News module | 🟦 Intentional Difference | Shared session_taste infra has Redis; module-level Redis not implemented in either |
| Database writes | ✅ Comprehensive (all interaction types, counters) | ✅ Good coverage | ✅ Complete | |
| Background jobs | ✅ 3 jobs: expiry, popular-sync, taste-update, ignore-detect | ✅ 3 jobs: pipeline (ingest+enrich), trending, archive | ✅ Complete | Different jobs by nature; Post: recommendation maintenance; News: ingestion + trending |
| Search | ❌ Not implemented | ❌ Not implemented | ❌ Missing (both) | |
| Embeddings (vector search) | ✅ pgvector 10-dim embeddings, HNSW | ❌ Not implemented | ❌ Missing | News has no embeddings for personalised ranking |
| Classification | 🟦 N/A (user content) | ✅ LLM classification via Groq | 🟦 Intentional Difference | |
| Metadata enrichment | 🟦 N/A | ✅ summary_bullets, impact, factor_scores | 🟦 Intentional Difference | |
| Personalisation | ✅ Multi-factor: category, commodity, author, geo, freshness, social | ❌ Role score computed but feed not personalised | ❌ Missing | |
| API response structure | ✅ FeedPostCard (rich author info + viewer state) | ✅ NewsCard (source info + viewer state) | ✅ Complete | Different content, same pattern |
| Permissions/auth | ✅ profile_id + user_id per endpoint | ✅ profile_id + user_id per endpoint | ✅ Complete | |
| Input validation | ✅ Pydantic validators, enum enforcement | ✅ Pydantic validators, enum enforcement | ✅ Complete | |
| Error handling | ✅ Custom exceptions, HTTP status codes | ✅ Custom exceptions, HTTP status codes | ✅ Complete | |
| Recommendation refresh | ✅ Every request generates fresh pool (no staleness) | ❌ No personalised recommendation to refresh | ❌ Missing | |
| Recommendation decay | ✅ 30-day seen exclusion, partition expiry, taste decay | ❌ No recommendation decay | ❌ Missing | |
| Ranking algorithm | ✅ Multi-signal composite formula | ❌ Reverse-chronological only | ❌ Missing | |
| Weight calculations | ✅ Category, commodity, author, freshness, engagement | ❌ Not computed at feed time | ❌ Missing | |
| Candidate generation | ✅ ANN + popular + fresh inject | ❌ All enriched articles are candidates | ❌ Missing | |
| Filtering pipeline | ✅ seen-exclusion, is_active, target_roles, diversity cap | ⚠️ is_active, enriched-only, geo/gov filters | ⚠️ Partial | No seen-exclusion, no diversity cap |
| Session taste update on interaction | ✅ Synchronous (like/save/share/comment/revisit) | ✅ Synchronous for like/save/share/revisit | ✅ Complete | |
| Global taste update on interaction | ❌ Not wired (infrastructure exists) | ❌ Not wired | ❌ Missing (both) | |
| Async interaction jobs | ✅ run_taste_update_job (dwell+open events, every 15 min) | ❌ No async taste-update job | ❌ Missing | NewsInteractionEvent.processed_at exists but no job reads it |
| Popularity metric | ✅ popular_posts table with velocity_score | ✅ NewsTrending table with velocity_score | ✅ Complete | Both compute velocity as weighted signals / hours |
| Following feed | ✅ /posts/following with social scoring | 🟦 N/A | 🟦 Intentional Difference | News is not user-authored |
| Comment feature | ✅ Full comment CRUD | ❌ Not implemented | 🟦 Intentional Difference | Users cannot comment on news (by design) |
| Deal/rich content type | ✅ PostDealDetails with close/reopen | 🟦 N/A | 🟦 Intentional Difference | |

---

## Phase 4: Intentional Differences

**1. Ingestion Pipeline**
News is ingested from external providers (GNews API) via a scheduled pipeline; Posts are created by platform users. News cannot have a "create post" flow. The ingestion module (`ingestion/`, `intelligence/`) has no equivalent in Post.

**2. Immutability**
News articles are immutable once ingested — they cannot be edited or deleted by a user. Post supports PATCH and DELETE by the author. This is correct domain behavior.

**3. No Author Concept for News**
News articles have a `source_name` and `source_url` but no `profile_id` author on the platform. Author affinity (which is central to Post) is therefore irrelevant for News. Source affinity is the correct analog, and the model supports it (`dimension_type='source'`) — but it is not yet implemented.

**4. Classification/Intelligence Pipeline**
Posts are user-crafted — no LLM classification is needed. News requires `EnrichedArticle` before it can be served. The `intelligence/` module (Groq, system prompt, factor taxonomy) is News-specific and correct.

**5. Comments on News**
Users cannot comment on news articles. This is a deliberate product decision. No `news_comments` table or comment endpoints exist, and this is not a gap.

**6. No Image Upload for News**
News articles have `image_url` from the provider; no signed upload URL mechanism is needed.

**7. Geo-category Taxonomy**
News uses `geo_category` (global | domestic) and `is_government` Boolean as filter axes, determined by LLM classification. Posts use physical `latitude/longitude` for vector-space geographic matching. These serve different purposes and cannot be unified.

**8. Deal/Requirement Content Type**
Post has `PostDealDetails` for deal/requirement posts with a `is_closed` lifecycle. News has no deal equivalent.

**9. Following Feed**
`GET /posts/following` shows posts from followed users. News has no equivalent because news articles are not authored by platform users.

**10. Dwell thresholds**
News readers dwell longer (article reading takes more time); the higher `DWELL_SHORT_MS` (15s vs 8s) and `DWELL_MEDIUM_MS` (60s vs 30s) thresholds are correctly calibrated for news reading patterns rather than social feed scrolling.

**11. Trending vs Popular**
Post uses `popular_posts` (velocity scored against total platform engagement over 30 days, commodity-filtered). News uses `NewsTrending` (velocity over last 6h, all-platform). The shorter window is correct for news (relevance decays faster).

---

## Phase 5: Missing Parity

### Area: Recommendation System

**[Gap 1] No Personalised News Recommendation Feed**
- What is missing: The `GET /news/recommendations/feed` endpoint is a router stub with a comment. No function returns a personalised ranked list of articles.
- Why it matters: All users see identical reverse-chronological feeds. Role score is computed and stored but never applied to ordering. A broker and a trader see the same articles in the same order.
- Where it exists in Post: `app/modules/post/post_recommendation_module/service.py:get_recommended_posts()`
- Where it should exist in News: `app/modules/news_new/news_recommendation_engine/router.py` + new `service.py` function that reads `user_news_taste`, computes scored ranking, and applies diversity caps
- Priority: Critical
- Confidence: High

**[Gap 2] Role Score Not Used for Feed Ordering**
- What is missing: `EnrichedArticle.role_trader/broker/exporter` is populated by the enrichment pipeline and attached to feed cards as `role_score`, but `get_trending_feed()` orders by `platform_arrived_at DESC` — role score has zero influence on sort order.
- Why it matters: A trader sees supply disruption articles that are far more relevant to a broker first; an exporter's feed is identical to a trader's despite different `RELEVANCY_MATRIX` weights.
- Where it exists in Post: `app/modules/post/post_recommendation_module/service.py:_rerank()` — category weight, commodity multiplier, freshness, engagement all applied.
- Where it should exist in News: `app/modules/news_new/feed/service.py:get_trending_feed()` — sort/rerank by role_score × freshness × engagement before pagination.
- Priority: Critical
- Confidence: High

**[Gap 3] No ANN / Vector Embeddings for News**
- What is missing: No `news_embeddings` table, no vector search. Candidate generation for News is "all enriched articles"; there is no semantic matching with user interest vectors.
- Why it matters: Without embeddings, a recommendation feed cannot find semantically relevant articles beyond the blunt role_score.
- Where it exists in Post: `app/modules/post/post_recommendation_module/models.py:PostEmbedding` + `service.py:_query_partition()` with pgvector HNSW search.
- Where it should exist in News: `app/modules/news_new/news_recommendation_engine/models.py` (a `NewsEmbedding` table) + query service. For News, embeddings could be text-based (BERT/OpenAI) rather than the domain-specific 10-dim vector Post uses.
- Priority: High (long-term)
- Confidence: High

**[Gap 4] No Commodity Affinity for News**
- What is missing: `user_news_taste` supports `dimension_type='commodity'` structurally, but no code writes commodity taste. `_taste_from_article()` only writes category. The feed does not filter or boost by user commodity.
- Why it matters: A rice trader sees cotton news first; a cotton trader sees the same feed. Commodity is the most important personalisation dimension on a commodity trading platform.
- Where it exists in Post: `app/modules/post/post_user_interaction/service.py:record_interaction()` writes `dimension_type='commodity', dimension_key=str(commodity_id)`. Reranker uses it via `_commodity_multiplier()`.
- Where it should exist in News: `app/modules/news_new/news_user_interaction/service.py:_taste_from_article()` should also write commodity taste when `EnrichedArticle` can supply commodity signals. `EnrichedArticle.factor_scores` + keyword extraction from title could provide commodity signals.
- Priority: High
- Confidence: High

**[Gap 5] No Source/Author Affinity Writes**
- What is missing: `user_news_taste` has `dimension_type='source'` in `TASTE_DIMENSIONS` but nothing writes source taste. `_taste_from_article()` ignores `RawArticle.source_name`.
- Why it matters: Users who regularly engage with Reuters or mint.com should see those sources boosted. This is the News analog of Post's author affinity.
- Where it exists in Post: `app/modules/post/post_user_interaction/service.py:record_interaction()` writes `dimension_type='author'` for signals with pos_delta >= 2.0.
- Where it should exist in News: `app/modules/news_new/news_user_interaction/service.py:_taste_from_article()` should write `dimension_type='source'` with `dimension_key=source_name` alongside category.
- Priority: Medium
- Confidence: High

**[Gap 6] No Seen-Article Exclusion from News Feed**
- What is missing: `news_views` tracks per-user article views, but `get_trending_feed()` does not exclude already-viewed articles. The same articles appear on every feed load.
- Why it matters: Infinite scroll becomes useless — page 2 shows the same articles as page 1 once seen. Post's `seen_posts` mechanism prevents this.
- Where it exists in Post: `app/modules/post/post_recommendation_module/service.py:_seen_post_ids()` + `pool_exclude` filtering. Also applied in `get_following_feed()`.
- Where it should exist in News: `app/modules/news_new/feed/service.py:get_trending_feed()` should query `news_views` (or a new `seen_news_articles` table) and exclude seen article IDs from the feed query.
- Priority: High
- Confidence: High

**[Gap 7] No Popular/Trending Articles Injected into Main Feed**
- What is missing: `NewsTrending` table is computed every 5 min with velocity scores, but `get_trending_feed()` ignores it entirely — the feed name is misleading. Trending articles have no preferential placement.
- Why it matters: High-velocity articles (many users engaged within 6h) should surface regardless of publication timestamp.
- Where it exists in Post: `app/modules/post/post_recommendation_module/service.py:_get_popular_posts()` injects `POPULAR_LIMIT=30` popular posts into the candidate pool at every feed load.
- Where it should exist in News: `app/modules/news_new/feed/service.py` should load `NewsTrending` articles and include them in (or boost them in) the feed, similar to Post's popular pool injection.
- Priority: High
- Confidence: High

**[Gap 8] No Fresh Article Injection**
- What is missing: Post guarantees articles < 4h old are in the candidate pool (`_ensure_fresh_in_pool`). News has no equivalent — a very recent article with a low publication rank might be buried.
- Why it matters: Breaking/urgent news published recently must surface immediately, not hours later.
- Where it exists in Post: `app/modules/post/post_recommendation_module/service.py:_ensure_fresh_in_pool()` with `FRESH_INJECT_HOURS=4`, `FRESH_SLOTS=5`.
- Where it should exist in News: News feed service, with `platform_arrived_at >= now - 4h` injection logic.
- Priority: Medium
- Confidence: High

---

### Area: Interaction System

**[Gap 9] No Async Taste Update Job for Dwell Events**
- What is missing: `NewsInteractionEvent` has `processed_at` column and the same queue pattern as Post, but no `run_taste_update_job()` equivalent exists for News. Dwell events from the batch endpoint are stored but never processed into taste.
- Why it matters: The largest volume of implicit engagement signals (dwell, open_article) never update taste. Taste effectively reflects only explicit interactions (like/save/share/revisit).
- Where it exists in Post: `app/modules/post/post_user_interaction/jobs.py:run_taste_update_job()` processes dwell and open_* events every 15 min.
- Where it should exist in News: `app/modules/news_new/news_user_interaction/jobs.py:run_taste_update_job()` — the pattern is identical; just needs to read `NewsInteractionEvent` instead of `PostInteractionEvent` and write `user_news_taste`.
- Priority: High
- Confidence: High

**[Gap 10] No Ignore Detection Job**
- What is missing: Post has `run_ignore_detection_job()` that applies negative taste for articles shown N+ times with zero engagement. News has no equivalent.
- Why it matters: Without negative signals from repeated ignoring, the taste profile can only grow in positive directions, making recommendations stale.
- Where it exists in Post: `app/modules/post/post_user_interaction/jobs.py:run_ignore_detection_job()`.
- Where it should exist in News: `app/modules/news_new/news_user_interaction/jobs.py:run_ignore_detection_job()`.
- Priority: Medium
- Confidence: High

**[Gap 11] Seen Threshold for Dwell Not Applied in News Batch**
- What is missing: `process_interaction_batch()` in News (`service.py`) does NOT upsert seen records on dwell >= `DWELL_SEEN_MS`. The `DWELL_SEEN_MS=5000` constant is defined but never used in the service.
- Why it matters: Articles are never marked as "seen" via dwell, so the seen-exclusion mechanism (if ever implemented) would have no data to work with.
- Where it exists in Post: `app/modules/post/post_user_interaction/service.py:process_interaction_batch()` lines 138–162 — upserts `seen_posts` for dwell >= 3,000ms.
- Where it should exist in News: `app/modules/news_new/news_user_interaction/service.py:process_interaction_batch()` — upsert `news_views` (or a `seen_news_articles` table) for dwell >= `DWELL_SEEN_MS`.
- Priority: High
- Confidence: High

**[Gap 12] View Count Not Incremented in Batch Processing**
- What is missing: When `open_article` events arrive in the batch, `upsert_view()` is called (which updates `NewsView.view_count`), but `NewsArticleStats.view_count` is NOT incremented. The stats counter is only updated if the service were to call `_adjust_stats(..., "view_count", 1)`.
- Why it matters: `NewsCardDetail.view_count` returns stale/zero data for most articles.
- Where it exists in Post: `app/modules/post/service.py:_record_view()` increments `Post.view_count` atomically on every first view.
- Where it should exist in News: `app/modules/news_new/news_user_interaction/service.py:upsert_view()` should call `_adjust_stats(db, article_id, "view_count", 1)` for new views (not revisits, to match Post's counter semantics).
- Priority: Medium
- Confidence: High

---

### Area: Feed System

**[Gap 13] Saved Feed Cursor Applied In-Memory**
- What is missing: `get_saved_feed()` loads ALL saved article IDs for the user, fetches all articles, then applies cursor in memory. For users with many saves, this is O(n) in memory.
- Why it matters: Performance degrades with save count. Post's saved feed uses DB-level cursor filtering (`PostSave.id < cursor_save_id`).
- Where it exists in Post: `app/modules/post/service.py:get_saved_posts()` — `PostSave.id < cursor_save_id` in the query.
- Where it should exist in News: `app/modules/news_new/feed/service.py:get_saved_feed()` — paginate `NewsSave` by `NewsSave.id < cursor` at DB level.
- Priority: Low
- Confidence: High

**[Gap 14] No Diversity Cap on News Feed**
- What is missing: News feed has no `MAX_PER_CATEGORY` or `MAX_PER_SOURCE` cap. A single topic (e.g., rice price) can dominate the entire page.
- Why it matters: Feed variety is poor for users tracking multiple commodities.
- Where it exists in Post: `app/modules/post/post_recommendation_module/service.py:_apply_diversity()` — `MAX_PER_CATEGORY=8`, `MAX_PER_AUTHOR=3`.
- Where it should exist in News: `app/modules/news_new/feed/service.py` — apply a `MAX_PER_FACTOR` and `MAX_PER_SOURCE` cap after the ranked list is built.
- Priority: Medium
- Confidence: High

**[Gap 15] `get_trending_feed` Name is Misleading**
- What is missing: Despite being named `get_trending_feed`, the function serves reverse-chronological articles and entirely ignores the `NewsTrending` table.
- Why it matters: Causes confusion; developers may assume trending is being applied.
- Where it should be: The function should either be renamed to `get_chronological_feed` or updated to incorporate `NewsTrending` article boosting.
- Priority: Low
- Confidence: High

---

### Area: Background Jobs

**[Gap 16] No Job Trigger Endpoints for News**
- What is missing: News has no `POST /news/interactions/jobs/taste-update` or `POST /news/interactions/jobs/ignore-detect` endpoints to manually trigger background jobs. The jobs that do exist (trending) are scheduled only.
- Why it matters: Cannot manually run jobs during development/debugging without scheduler access.
- Where it exists in Post: `app/modules/post/post_user_interaction/router.py` exposes job trigger endpoints.
- Where it should exist in News: `app/modules/news_new/news_user_interaction/router.py`.
- Priority: Low
- Confidence: High

---

### Area: Caching

**[Gap 17] `FeedRankingCache` Not Wired to Any Endpoint**
- What is missing: `ArticleRecommendationScore` and `FeedRankingCache` tables exist with full models and service functions (`upsert_recommendation_score`, `upsert_feed_ranking_cache`), but no endpoint reads from them.
- Why it matters: The cache infrastructure is dead code currently; no request path benefits from it.
- Where it exists in Post: Post uses `popular_posts` and partition-based indexes (both are actively queried). No direct equivalent to `FeedRankingCache`, but the separation is cleaner.
- Where it should exist in News: The personalised recommendation endpoint (Gap 1) should read from / write to `FeedRankingCache` on every request.
- Priority: Medium (depends on Gap 1)
- Confidence: High

---

## Phase 6: Implementation Roadmap

### Step 1: Fix Dwell Seen-Marking in News Batch
- **What**: In `app/modules/news_new/news_user_interaction/service.py:process_interaction_batch()`, after inserting `NewsInteractionEvent` rows, check `event_type == "dwell" AND value_ms >= DWELL_SEEN_MS` and call `upsert_view()` (or upsert into a dedicated seen table).
- **Why**: Critical data foundation — seen history is required for deduplication and async taste updates.
- **Files**: `app/modules/news_new/news_user_interaction/service.py`
- **Depends on**: Nothing

### Step 2: Fix View Count in Stats
- **What**: In `service.py:upsert_view()`, call `_adjust_stats(db, article_id, "view_count", 1)` for new views (when `view is None`).
- **Why**: `NewsCardDetail.view_count` returns wrong data currently.
- **Files**: `app/modules/news_new/news_user_interaction/service.py`
- **Depends on**: Nothing

### Step 3: Add Commodity Affinity Write
- **What**: In `_taste_from_article()`, look up `EnrichedArticle.factor_scores` and map factors to commodity tags. Write `dimension_type='commodity'` taste row for the user's primary commodities when a factor signals that commodity.
- **Why**: Without commodity signals, the most critical dimension for a trading platform is absent from taste.
- **Files**: `app/modules/news_new/news_user_interaction/service.py`, `app/modules/news_new/news_user_interaction/taste_service.py` (no changes needed)
- **Depends on**: Step 1 (for dwell-driven commodity taste)

### Step 4: Add Source Affinity Write
- **What**: In `_taste_from_article()`, read `RawArticle.source_name` and write `dimension_type='source'` taste row for signals with `pos_delta >= 2.0` (like, save, share, revisit).
- **Why**: Source affinity is the News analog of Post's author affinity.
- **Files**: `app/modules/news_new/news_user_interaction/service.py`
- **Depends on**: Nothing

### Step 5: Implement Async Dwell Taste Update Job
- **What**: Create `app/modules/news_new/news_user_interaction/jobs.py:run_taste_update_job()` that processes unprocessed `NewsInteractionEvent` rows (dwell, open_article), derives signals, and writes to `user_news_taste`. Mirror Post's `run_taste_update_job()` pattern.
- **Why**: Largest volume of implicit signals never enters taste without this job.
- **Files**: `app/modules/news_new/news_user_interaction/jobs.py`
- **Depends on**: Step 3, Step 4 (for complete taste writes)

### Step 6: Add Ignore Detection Job for News
- **What**: Create `run_ignore_detection_job()` in `app/modules/news_new/news_user_interaction/jobs.py`. Mirror Post's equivalent using `NewsInteractionEvent` and `user_news_taste`.
- **Why**: Negative signals needed for taste to self-correct.
- **Files**: `app/modules/news_new/news_user_interaction/jobs.py`
- **Depends on**: Step 5

### Step 7: Add Job Trigger Endpoints for News
- **What**: Add `POST /news/interactions/jobs/taste-update` and `POST /news/interactions/jobs/ignore-detect` in `router.py`.
- **Why**: Operational observability and manual testing.
- **Files**: `app/modules/news_new/news_user_interaction/router.py`
- **Depends on**: Step 5, Step 6

### Step 8: Add Seen-Article Exclusion from News Feed
- **What**: In `app/modules/news_new/feed/service.py:get_trending_feed()`, query `news_views` for the profile's seen article IDs and add a `.where(RawArticle.id.notin_(seen_ids))` clause (or a rolling window like Post's 30-day limit).
- **Why**: Without exclusion, users see the same articles on every page load.
- **Files**: `app/modules/news_new/feed/service.py`
- **Depends on**: Step 1 (so seen data exists)

### Step 9: Integrate Trending Articles into Feed
- **What**: In `app/modules/news_new/feed/service.py:get_trending_feed()`, additionally fetch `NewsTrending` article IDs (ordered by `velocity_score DESC`) and inject them into the candidate pool before final sort. Apply freshness decay to the sort score.
- **Why**: `NewsTrending` is computed every 5 min but unused.
- **Files**: `app/modules/news_new/feed/service.py`
- **Depends on**: Step 8 (to avoid re-serving trending articles already seen)

### Step 10: Apply Role Score to Feed Ordering
- **What**: In `get_trending_feed()`, compute `final_score = role_score × freshness_factor` and sort by `final_score DESC` instead of `platform_arrived_at DESC`. Use `EnrichedArticle.role_trader/broker/exporter` for role_score lookup.
- **Why**: Role-relevance filtering is the minimum viable personalisation step; no new infrastructure needed.
- **Files**: `app/modules/news_new/feed/service.py`
- **Depends on**: Step 8, Step 9

### Step 11: Add Diversity Cap to News Feed
- **What**: After generating the ranked article list, apply `MAX_PER_FACTOR` and `MAX_PER_SOURCE` caps before returning the page.
- **Why**: Feed variety across topics and sources.
- **Files**: `app/modules/news_new/feed/service.py`
- **Depends on**: Step 10

### Step 12: Implement Personalised News Recommendation Feed
- **What**: Implement `app/modules/news_new/news_recommendation_engine/service.py` with a `get_recommended_news()` function that reads `user_news_taste`, weights category × commodity × source, scores all enriched articles, applies diversity caps, and returns a personalised page. Wire to `GET /news/recommendations/feed`.
- **Why**: True personalisation — the main gap vs Post.
- **Files**: `app/modules/news_new/news_recommendation_engine/router.py`, new service function, `app/modules/news_new/news_recommendation_engine/service.py`
- **Depends on**: Steps 3–5 (taste data), Step 11 (diversity)

### Step 13: Fix Saved Feed Cursor (DB-Level)
- **What**: Refactor `get_saved_feed()` to paginate `NewsSave` at DB level using `NewsSave.id < cursor_id` pattern (matching Post's saved feed implementation).
- **Why**: Performance with many saves.
- **Files**: `app/modules/news_new/feed/service.py`
- **Depends on**: Nothing

---

## Phase 7: Final Summary

### What News Does Correctly

- **Full ingestion pipeline**: GNews fetch → canonical normalisation → dedup → `RawArticle` storage works correctly
- **LLM classification**: Groq-based enrichment with retry, enum validation, and role relevance matrix computation is robust
- **All explicit interactions**: Like, save, share (both external and in-app chat delivery), view tracking — all complete and matching Post's pattern
- **Category taste infrastructure**: `user_news_taste` + `taste_service` with exponential decay, cold-start bootstrap, and role defaults — correctly mirrors Post's `user_post_taste`
- **Cursor pagination**: Keyset pagination on `(platform_arrived_at, id)` is correct and more robust than Post's integer cursor for high-concurrency scenarios
- **Filtered feeds**: `/news/feed/global`, `/news/feed/domestic`, `/news/feed/government` work correctly via `EnrichedArticle` filter push-down
- **Trending job**: `recalc_trending()` correctly computes velocity from recent interactions across all signal types
- **Archive job**: Soft-deletes old articles after 30 days
- **In-app share**: Full chat delivery for news articles (DM + group), matching Post's implementation
- **Response structure**: `NewsCard` and `NewsCardDetail` are well-structured with enrichment metadata

### What News Intentionally Does Differently (Justified)

- **No user-authored content**: Articles are ingested from providers — Create/Update/Delete by users is inappropriate
- **Intelligence pipeline**: LLM classification + summarization has no Post equivalent — justified by immutable, unstructured external content
- **Geo taxonomy**: `geo_category` + `is_government` vs Post's lat/lon vectors — correct for editorial classification vs physical location
- **No comments**: Users don't comment on news articles — product decision
- **Higher dwell thresholds**: Reading an article takes longer than reading a post caption — correct calibration
- **Shorter trending window (6h vs 30-day)**: News relevance decays faster — correct
- **Following feed**: N/A — news is not user-authored

### What News Still Lacks

- **Personalised recommendation feed**: All users see the same reverse-chronological list; `GET /news/recommendations/feed` is a stub
- **Role score not applied to ordering**: Computed but never used as a sort key
- **Seen-article exclusion**: Users see the same articles on every page load; no deduplication
- **Async dwell taste update**: Dwell events stored but never processed into taste profiles
- **Commodity taste**: Most important dimension for a commodity trading platform is absent
- **Trending/popular article injection**: `NewsTrending` computed every 5 min but unused in feed
- **Feed freshness boost**: No explicit multiplier for recently arrived articles
- **Diversity cap**: No per-factor or per-source cap; single topic can dominate
- **Ignore detection**: No negative signal job for repeatedly ignored articles
- **Source affinity**: Structurally supported but never written

### Top 3 Next Steps

1. **Apply role score to feed ordering** (Step 10): Minimum viable personalisation with zero new infrastructure — single change to `get_trending_feed()` sort key delivers immediate lift.
2. **Add seen-article exclusion** (Step 8): Fundamental UX fix — users currently see the same page on every reload. Requires fixing dwell seen-marking (Step 1) first.
3. **Implement async dwell taste update job** (Step 5): Unlocks the largest volume of implicit signals and makes `user_news_taste` data meaningful for the eventual personalised feed.

---

### Parity Estimates

| Area | Parity |
|---|---|
| Recommendation System | 10% |
| Interaction System | 65% |
| Feed Generation | 35% |
| Filtering | 55% |
| Caching | 20% |
| Background Jobs | 60% |
| API Design | 80% |
| **Overall** | **46%** |

---

_Audit based exclusively on source code read on 2026-06-24. All conclusions are derived from executable code only. No behaviour was inferred from names alone._
