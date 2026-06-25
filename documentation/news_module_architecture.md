# News Module Architecture

Complete orchestration of `app/modules/news_new/` — every sub-module, its models, its workflow, and how it connects to the rest of the system.

---

## Module Map

```
news_new/
├── config.py                          # taxonomy, matrix, enums, prompts, provider config
├── ingestion/                         # fetch raw articles from GNews
│   ├── models.py                      # RawArticle
│   ├── service.py                     # fetch, normalize, dedup, rotate queries
│   ├── router.py                      # admin: ingest, enrich, stats
│   ├── jobs.py                        # run_news_pipeline, archive_old_articles
│   ├── news_queries.py                # 30-query rotation pool
│   └── providers/
│       ├── base.py                    # BaseNewsProvider, ProviderQuotaError
│       └── gnews.py                   # GNewsProvider (free tier, 100 req/day)
├── intelligence/                      # enrich raw articles via LLM
│   ├── models.py                      # EnrichedArticle
│   ├── service.py                     # enrich_article, enrich_pending
│   ├── schemas.py                     # LLMEnrichment (Pydantic validation)
│   └── providers/
│       └── groq.py                    # GroqEnricher, RateLimiter
├── news_user_interaction/             # engagement events, likes, saves, trending
│   ├── models.py                      # NewsInteractionEvent, NewsView, NewsLike, NewsSave,
│   │                                  # NewsShare, NewsArticleStats, NewsTrending,
│   │                                  # UserNewsTaste, UserNewsTasteProfile
│   ├── service.py                     # process_interaction_batch, toggle_like/save, send_article
│   ├── taste_service.py               # update_taste, get_taste_weights, seed_taste_from_role
│   ├── jobs.py                        # recalc_trending (5-min)
│   ├── router.py                      # POST batch, like, save, share, send
│   ├── constants.py                   # signal weights, dwell thresholds, decay lambda
│   └── schemas.py
├── news_recommendation_engine/        # scoring helpers
│   ├── profile_scorer.py              # Layer 2: commodity + state affinity
│   ├── service.py                     # score upsert, cache management
│   ├── models.py                      # ArticleRecommendationScore, FeedRankingCache
│   └── interfaces.py
└── feed/                              # assemble and serve feeds to clients
    ├── router.py                      # GET /news/feed, /trending, /saved, /global, etc.
    ├── service.py                     # get_recommended_feed, get_trending_news, etc.
    └── schemas.py                     # NewsCard, NewsCardDetail, NewsFeedPage
```

---

## Central Config (`config.py`)

Single source of truth — no other file defines taxonomy or weights.

### 10-Factor Taxonomy

| ID | Slug | Description |
|----|------|-------------|
| 1 | `policy_regulation` | Govt/regulator actions on trade & commodities — tariffs, MSP, export bans |
| 2 | `geopolitical_macro` | War, sanctions, forex, macro shocks |
| 3 | `supply_disruptions` | Weather, crop yield, logistics, port, production shocks |
| 4 | `financial_mechanics` | Interest rates, credit, margin/derivative rules |
| 5 | `structural_shifts` | Long-run industry/tech change |
| 6 | `long_term_demand` | Slow consumption/demand trends |
| 7 | `deal_flow` | Tenders, contracts, trade volumes, shipments |
| 8 | `price_volatility` | Sentiment-only price moves (no stated cause) |
| 9 | `local_operational` | Mandi/APMC operational events |
| 10 | `indirect_general` | Fallback — nothing else fits |

### Relevancy Matrix (Layer 1 weights, pre-computed at ingest)

| Factor | Trader | Broker | Exporter |
|--------|--------|--------|----------|
| policy_regulation | 9.0 | 9.2 | 9.8 |
| geopolitical_macro | 8.7 | 8.4 | 9.5 |
| supply_disruptions | 7.3 | 9.0 | 8.8 |
| financial_mechanics | 5.8 | 6.8 | 7.5 |
| structural_shifts | 4.2 | 6.2 | 6.8 |
| long_term_demand | 3.2 | 4.5 | 5.8 |
| deal_flow | 6.5 | 9.3 | 7.2 |
| price_volatility | 8.5 | 9.0 | 7.0 |
| local_operational | 5.5 | 8.5 | 6.8 |
| indirect_general | 4.5 | 5.5 | 5.8 |

Role IDs: 1=Trader, 2=Broker, 3=Exporter.

### Closed Enums

- `GEO_CATEGORIES`: `global` | `domestic`
- `IMPACT_DIRECTIONS`: `positive` | `neutral` | `negative`
- `intelligence_status` lifecycle: `pending` → `enriched` | `failed`

### Rate Limits

| System | Limit | Config |
|--------|-------|--------|
| GNews free tier | 100 req/day | 2 queries/run × 48 runs/day = 96 |
| Groq enrichment | 30 req/min, 6K tpm | 2 articles/min pacing |
| Enrichment batch | 20 articles/run | `ENRICH_BATCH_LIMIT` |
| Content cap sent to LLM | 1000 chars | `LLM_CONTENT_CHAR_CAP` |

---

## Sub-Module 1: Ingestion

### Purpose
Fetch raw articles from GNews, normalize to `RawArticle`, store with `status=pending`.

### Key Model: `RawArticle` (`news_raw_articles`)

```
id (UUID PK)
external_id (unique — deduplication key)
title, description, content
article_url, image_url, source_url, source_name, source_country
published_at, language
authors (JSONB)
intelligence_status: pending | enriched | failed
is_active (soft-delete flag)
platform_arrived_at (when we received it)
raw_metadata (JSONB — full provider payload for audit/replay)
```

### Query Pool (`news_queries.py`)

30 pre-curated Boolean GNews queries across:
- Commodity lanes: rice, wheat, sugar, cotton, soybean, edible oils, pulses, spices
- Policy lanes: export ban, import duty, MSP, FCI procurement
- Macro lanes: RBI, rupee, sanctions, USDA crop
- Deal flow: tender, cargo, shipment
- Each query has a `country` field: `"in"` (domestic bias) or `None` (global)

Time-slot rotation: queries are distributed across 30-min slots so no two runs hit the same queries consecutively. This spreads coverage evenly and avoids rate-limit spikes.

### Workflow

```
Scheduled every 30 min (run_news_pipeline)
│
├── select_queries_for_run()
│     — picks 2 queries from the rotation based on current time slot
│
├── For each query:
│     GNewsProvider.fetch(query, country)
│     → HTTP GET to GNews API
│     → on 429: exponential backoff, retry up to 3 times
│     → on 403: ProviderQuotaError (daily cap hit, stop run)
│     → to_canonical(): normalize GNews fields to standard dict
│
├── For each canonical article:
│     — check external_id uniqueness (skip duplicates)
│     — insert RawArticle(status=pending, platform_arrived_at=now)
│     — commit per batch
│
└── Returns: {fetched, inserted, skipped_duplicate, quota_hit}
```

### Admin Endpoints (`POST /news/admin/`)

| Endpoint | Action |
|----------|--------|
| `POST /news/admin/ingest` | Trigger single query or rotation |
| `POST /news/admin/enrich` | Enrich up to N pending articles |
| `GET /news/admin/stats` | Count by intelligence_status |

---

## Sub-Module 2: Intelligence

### Purpose
Enrich each `RawArticle` with LLM-driven classification, summary, impact scoring, commodity tags, and state tags. Write one `EnrichedArticle` row. Compute role relevance from the matrix (never from the LLM).

### Key Model: `EnrichedArticle` (`news_enriched_articles`)

```
id (UUID PK)
raw_article_id (FK → news_raw_articles, unique)

# LLM classification
primary_factor (slug from taxonomy)
factor_scores (JSONB — [{factor, score}] for top 2–3 factors)
geo_category: global | domestic
is_government (boolean — independent of geo and factor)

# LLM summary and impact
summary_bullets (JSONB — exactly 3 concrete facts)
impact_direction: positive | neutral | negative
impact_score (0–10)
impact_factor (short label, e.g. "Export ban")
impact_explanation (one sentence)

# Layer 2 profile tags (LLM-extracted)
commodity_tags (JSONB — commodity names verbatim from text)
state_tags (JSONB — Indian states verbatim from text)

# Layer 1 role relevance (COMPUTED from RELEVANCY_MATRIX, not from LLM)
role_trader   (float)
role_broker   (float)
role_exporter (float)

model_version, generated_at
```

### LLM System Prompt

Single Groq call per article returns a JSON object with all fields above. The prompt includes:
- Closed-enum enforcement for `primary_factor`, `geo_category`, `impact.direction`
- Decision procedure (9 ordered steps)
- Tie-break rules (driver over symptom; government actor ≠ policy_regulation)
- Two worked examples (one domestic policy, one global supply shock)
- LOW SIGNAL fallback (sparse articles → `indirect_general`, score ≤ 2)

### Workflow

```
run_news_pipeline (30-min, continues after ingest)
│
├── enrich_pending(limit=20)
│     — fetches up to 20 RawArticles with status=pending
│
├── For each article:
│     build_input_text()
│     → "TITLE: ...\nDESCRIPTION: ...\nCONTENT: ...(capped 1000 chars)"
│
│     GroqEnricher.enrich(text)
│     → POST to Groq API (llama-3.1-8b-instant, temp=0.2, JSON mode)
│     → RateLimiter: bucket fill at 2/min, blocks if needed
│     → on 429: exponential backoff, up to 5 retries
│
│     LLMEnrichment.model_validate(raw)
│     → validates all closed enums
│     → on failure: retry once, then mark article status=failed
│
│     role_relevance_for(primary_factor)
│     → pure dict lookup from RELEVANCY_MATRIX (no LLM involvement)
│
│     INSERT EnrichedArticle(all fields)
│     UPDATE RawArticle.status = enriched
│     commit()   ← per article for crash safety
│
└── Returns: {enriched, failed, groq_calls, remaining_pending}
```

---

## Sub-Module 3: News User Interaction

### Purpose
Record user engagement (events, likes, saves, shares), maintain per-article stats counters, compute user taste profiles, and run the velocity-based trending job.

### Key Models

| Model | Table | Purpose |
|-------|-------|---------|
| `NewsInteractionEvent` | `news_interaction_events` | Raw event log (impression, dwell, open_article, share_tap) |
| `NewsView` | `news_views` | One row per profile+article; tracks view_count, first/last viewed |
| `NewsLike` | `news_likes` | Toggle — one row while liked |
| `NewsSave` | `news_saves` | Toggle — one row while saved |
| `NewsShare` | `news_shares` | Append-only external share log |
| `NewsArticleStats` | `news_article_stats` | Pre-computed counters: view, like, save, share counts |
| `NewsTrending` | `news_raw_trending` | Velocity snapshot; written by job, read by feed |
| `UserNewsTaste` | `news_user_taste` | Per-profile per-dimension taste scores with decay |
| `UserNewsTasteProfile` | `news_user_taste_profiles` | Rolled-up summary (dominant factor, weights map) |

### Signal Weights (`constants.py`)

| Event | Signal | Weight |
|-------|--------|--------|
| impression | positive | 0.3 |
| dwell (short, 3–15s) | positive | 0.5 |
| dwell (medium, 15–60s) | positive | 1.5 |
| dwell (long, ≥60s) | positive | 3.0 |
| open_article | positive | 2.0 |
| share_tap | positive | 2.5 |
| revisit | positive | 6.0 |
| like | positive | 3.0 |
| save | positive | 4.0 |
| dislike | negative | 3.0 |

### Client Event Workflow

```
POST /news/interactions/batch
│
├── Validate: article_ids exist in news_raw_articles
├── For each event:
│     upsert NewsView (first_viewed, last_viewed, view_count++)
│     on open_article: detect revisit → record revisit event
│     bulk INSERT NewsInteractionEvent
│
└── Returns: {processed, invalid_article_ids}
```

### Like / Save / Share Workflow

```
POST /news/interactions/like/{article_id}   (toggle)
├── Toggle NewsLike row
├── UPDATE NewsArticleStats.like_count ± 1
└── update_taste(profile_id, primary_factor, delta)

POST /news/interactions/save/{article_id}   (toggle)
├── Toggle NewsSave row
├── UPDATE NewsArticleStats.save_count ± 1
└── update_taste(profile_id, primary_factor, delta)

POST /news/interactions/share/{article_id}  (external)
├── INSERT NewsShare
├── UPDATE NewsArticleStats.share_count + 1
└── update_taste(profile_id, primary_factor, delta)

POST /news/interactions/send/{article_id}   (in-app)
├── ChatRepository.save_message() to each DM/group
├── INSERT NewsShare + update_stats
├── update_taste(profile_id, primary_factor, delta)
└── Emit WebSocket event to recipients
```

### Taste Service

```
update_taste(profile_id, factor, delta)
├── UPSERT UserNewsTaste (ON CONFLICT DO UPDATE)
│     positive_score += delta.positive
│     negative_score += delta.negative
│     event_count++
└── Recalculate UserNewsTasteProfile if event_count crosses thresholds

get_taste_weights(profile_id, dimension)
├── Fetch UserNewsTaste rows for dimension
├── Apply 30-day exponential decay (lambda = ln2/30)
├── Floor at 0.05 (prevent total suppression)
└── Blend with role defaults until 20 events bootstrapped
```

### Trending Job (`recalc_trending`, every 5 min)

```
Look back: last 6 hours of NewsInteractionEvent + NewsLike + NewsSave + NewsShare

For each article in that window:
  weighted_signal_sum = Σ(event_type_weight × event_count)
  unique_profile_count = COUNT(DISTINCT profile_id)
  velocity_score = weighted_signal_sum / log1p(unique_profile_count)

UPSERT NewsTrending (article_id, velocity_score, trending_rank, computed_at)
DELETE rows below MIN_UNIQUE_USERS threshold
```

---

## Sub-Module 4: News Recommendation Engine

### Purpose
Provide scoring helpers used at request-time by the feed layer. Not a standalone service — called from `feed/service.py`.

### Layer 1: Role Score (pre-computed at ingest)

Stored directly on `EnrichedArticle` as `role_trader`, `role_broker`, `role_exporter`. Looked up at feed time via `_ROLE_COL = {1: "role_trader", 2: "role_broker", 3: "role_exporter"}`. No computation needed at request time.

### Layer 2: Profile Boost (`profile_scorer.py`)

Applied only on the recommended feed (`GET /news/feed`). Computed at request time.

```
_get_profile_context(db, profile_id)
├── SELECT Profile → role_id
├── SELECT Commodity.name JOIN Profile_Commodity → [commodity names]
└── SELECT Business.state → state

compute_commodity_score(user_commodities, article.commodity_tags)
└── Jaccard similarity: |user ∩ article| / |user ∪ article|
    Both sides lowercased+stripped. Returns 0.0 if either is empty.

compute_state_score(user_state, article.state_tags)
└── 1.0 if user_state in article.state_tags (lowercased), else 0.0

compute_profile_boost(user_commodities, user_state, enriched)
└── (0.25 × commodity_score) + (0.10 × state_score)
    Range: [0.0, 0.35]

apply_profile_boost(layer1_score, profile_boost)
└── round(layer1_score × (1 + profile_boost), 4)
    Multiplicative: Layer 1 stays the relevance floor.
    A commodity match cannot rescue a topically irrelevant article.
```

### Layer 3: Taste Score (placeholder)

`UserNewsTaste` and `UserNewsTasteProfile` models are written and populated by the interaction sub-module. The feed layer does not yet apply them. Deferred for Phase 3.

---

## Sub-Module 5: Feed

### Purpose
Assemble ranked or filtered article lists and serve them to the client.

### Endpoints

| Method | Path | Feed Type | Scoring |
|--------|------|-----------|---------|
| GET | `/news/feed` | Recommended — landing page | Layer 1 + Layer 2 |
| GET | `/news/trending` | Trending by velocity | None (velocity order) |
| GET | `/news/feed/saved` | User-saved articles | None (save order) |
| GET | `/news/feed/global` | geo_category = global | None (recency order) |
| GET | `/news/feed/domestic` | geo_category = domestic | None (recency order) |
| GET | `/news/feed/government` | is_government = true | None (recency order) |
| GET | `/news/articles/{id}` | Single article detail | None |

All feeds use `cursor_article_id: str | None` cursor pagination. `next_cursor = str(last_article.id) if len(page) == limit else None`.

### Recommended Feed Workflow (`GET /news/feed`)

```
get_recommended_feed(db, profile_id, limit, cursor_article_id)
│
├── _get_profile_context(db, profile_id)
│     → role_id, [commodity_names], state  (3 queries, all profile data in one fn)
│
├── Time-bucket pool collection:
│     Try ≤12h window → if candidates >= MIN_POOL_SIZE (30): use it
│     else expand to ≤24h → if >= 30: use it
│     else expand to ≤48h → use whatever exists
│     Articles older than 48h: never returned
│     Cap: up to 500 candidates fetched
│
├── Batch DB loads (4 queries for N candidates):
│     enriched_map   = { raw_article_id → EnrichedArticle }
│     stats_map      = { article_id → NewsArticleStats }
│     liked_ids      = { article_ids this user liked }
│     saved_ids_set  = { article_ids this user saved }
│
├── Score each candidate:
│     role_score = enriched.role_trader/broker/exporter (via _ROLE_COL)
│     profile_boost = compute_profile_boost(user_commodities, user_state, enriched)
│     final_score = role_score × (1 + profile_boost)
│
├── Sort all candidates by final_score DESC (scores stay server-side)
│
├── Cursor: find cursor_article_id position in ranked list → start = index + 1
│     (if article aged out of window: restart from 0)
│
├── Slice page = scored[start : start + limit]
│
└── Assemble NewsCards → NewsFeedPage(articles, next_cursor)
```

### Trending Feed Workflow (`GET /news/trending`)

```
get_trending_news(db, profile_id, limit, cursor_article_id)
│
├── Fetch ALL trending articles:
│     SELECT RawArticle JOIN NewsTrending
│     WHERE is_active=True AND velocity_score > 0
│     ORDER BY velocity_score DESC, platform_arrived_at DESC
│
├── Cursor: find position → start = index + 1
├── Slice page, compute next_cursor
│
└── _build_feed_page(db, page, profile_id)
      → batch load enriched/stats/liked/saved
      → assemble NewsCards
```

### Filtered Feed Workflow (`GET /news/feed/global` | `/domestic` | `/government`)

```
get_filtered_feed(db, profile_id, feed_filter, limit, cursor_article_id)
│
├── Fetch matching enriched_ids:
│     "global"/"domestic" → WHERE geo_category = feed_filter
│     "government"        → WHERE is_government = TRUE
│
├── DB query with time cursor:
│     lookup cursor article's platform_arrived_at (one extra query if cursor provided)
│     WHERE platform_arrived_at < ts OR (= ts AND id < cursor_id)
│     ORDER BY platform_arrived_at DESC, id DESC
│     LIMIT limit + 1
│
└── _build_feed_page → NewsCards → NewsFeedPage
```

### Response Schema

```python
class NewsCard:
    article_id: UUID
    title: str
    image_url: str | None
    source_name: str | None
    time_on_platform: str         # "3h", "Yesterday", "5 days ago"
    platform_arrived_at: datetime
    summary_bullets: list[str] | None
    primary_factor: str | None
    geo_category: str | None
    is_government: bool
    impact_direction: str | None
    impact_score: float | None
    like_count: int
    share_count: int
    is_liked: bool
    is_saved: bool

class NewsCardDetail(NewsCard):   # GET /news/articles/{id}
    description: str | None
    article_url: str
    source_url: str | None
    published_at: datetime
    impact_explanation: str | None
    impact_factor: str | None
    factor_scores: list | None
    view_count: int | None
    save_count: int | None

class NewsFeedPage:
    articles: list[NewsCard]
    next_cursor: str | None       # None = no more pages
```

---

## Scheduled Jobs

| Job | Cadence | What it does |
|-----|---------|--------------|
| `run_news_pipeline` | Every 30 min | Ingest rotation (2 queries) → enrich pending (up to 20 articles) |
| `recalc_trending` | Every 5 min | Recompute velocity scores from last 6h interactions |
| `archive_old_articles` | Daily 2 AM | Soft-delete articles older than 30 days (`is_active=False`) |

---

## End-to-End Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 1 — INGEST (every 30 min)                                     │
│                                                                     │
│  GNews API ──────────────────────────────────────────────────────── │
│  2 queries from rotation pool                                       │
│  ↓                                                                  │
│  GNewsProvider.fetch() → to_canonical()                             │
│  ↓                                                                  │
│  INSERT RawArticle (status=pending, platform_arrived_at=now)        │
│  Skip duplicates via external_id uniqueness constraint              │
└─────────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 2 — INTELLIGENCE (every 30 min, after ingest)                 │
│                                                                     │
│  SELECT up to 20 RawArticles WHERE status=pending                   │
│  ↓                                                                  │
│  build_input_text() → Groq LLM (single call per article)            │
│  ↓                                                                  │
│  LLMEnrichment validation (retry once on bad output)                │
│  ↓                                                                  │
│  role_relevance_for(primary_factor) → from RELEVANCY_MATRIX (static)│
│  ↓                                                                  │
│  INSERT EnrichedArticle (classification + summary + scores + tags)  │
│  UPDATE RawArticle.status = enriched | failed                       │
└─────────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 3 — USER INTERACTION (realtime, as user engages)              │
│                                                                     │
│  POST /news/interactions/batch   → NewsInteractionEvent, NewsView   │
│  POST /news/interactions/like    → NewsLike, NewsArticleStats       │
│  POST /news/interactions/save    → NewsSave, NewsArticleStats       │
│  POST /news/interactions/share   → NewsShare, NewsArticleStats      │
│  POST /news/interactions/send    → ChatMessage + NewsShare          │
│                                                                     │
│  Each action → update_taste() → UserNewsTaste (decay-aware upsert)  │
└─────────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 4 — TRENDING (every 5 min, background)                        │
│                                                                     │
│  Aggregate last 6h interactions                                     │
│  velocity = weighted_signal_sum / log1p(unique_profile_count)       │
│  UPSERT NewsTrending (article_id, velocity_score, computed_at)      │
└─────────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 5 — FEED (on-demand, per request)                             │
│                                                                     │
│  GET /news/feed  (recommended, landing page)                        │
│    profile context: role_id + commodity_names + state (3 queries)   │
│    pool: last 12/24/48h enriched articles (time-bucket expansion)   │
│    Layer 1: role_trader/broker/exporter from EnrichedArticle        │
│    Layer 2: Jaccard commodity × 0.25 + state match × 0.10           │
│    final_score = layer1 × (1 + profile_boost)                       │
│    sort DESC → slice by cursor → return NewsCards                   │
│                                                                     │
│  GET /news/trending                                                 │
│    JOIN NewsTrending ORDER BY velocity_score DESC                   │
│                                                                     │
│  GET /news/feed/global | /domestic | /government                    │
│    pure filter on geo_category or is_government                     │
│    ORDER BY platform_arrived_at DESC                                │
│                                                                     │
│  GET /news/articles/{id}                                            │
│    single article + enriched + stats + liked/saved flags            │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Router Registration

In `main.py`, a single `news_new_router` is imported from `app/modules/news_new/__init__.py` which includes four sub-routers:

| Sub-router | Prefix | Contains |
|------------|--------|---------|
| `ingestion/router.py` | `/news/admin` | Admin ingest/enrich/stats endpoints |
| `news_user_interaction/router.py` | `/news/interactions` | Like, save, share, send, batch |
| `news_recommendation_engine/router.py` | `/news/recommendation` | (placeholder) |
| `feed/router.py` | `/news` | All feed endpoints |

---

## What Is Complete vs Pending

| Component | Status |
|-----------|--------|
| Ingestion pipeline (GNews, rotation, dedup) | ✅ Complete |
| Intelligence pipeline (Groq, classification, enrichment) | ✅ Complete |
| `commodity_tags` + `state_tags` LLM extraction | ✅ Complete |
| Layer 1 role relevance (pre-computed at ingest) | ✅ Complete |
| Layer 2 commodity + state profile boost | ✅ Complete |
| `recalc_trending` velocity job | ✅ Complete |
| All 7 feed endpoints with cursor pagination | ✅ Complete |
| Interaction events (batch, like, save, share, send) | ✅ Complete |
| Taste signal recording (`UserNewsTaste`) | ✅ Complete |
| Layer 3 taste-driven feed scoring | ⏳ Pending (Phase 3) |
| `FeedRankingCache` usage | ⏳ Pending |
| Trending news separate endpoint | ✅ Complete (`GET /news/trending`) |
