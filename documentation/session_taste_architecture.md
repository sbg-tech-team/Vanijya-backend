# Session Taste Architecture — Complete Specification

> Status: Design finalized, pre-implementation  
> Scope: Post module (Phase 1). Same lifecycle applies to all future modules.  
> Date: 2026-06-22

---

## 1. The Problem Being Solved

The existing persistent taste system has a 15-minute lag. When a user sends dwell events via the batch endpoint, those signals sit in `post_interaction_events` with `processed_at = NULL` until the background job processes them. During that window the feed cannot adapt to what the user just read.

**Explicit interactions (like, save, comment, share) already update taste synchronously** — this problem only affects passive behavioral signals: dwell, open_read_more, open_carousel, open_comments, link_click.

Session taste closes this gap by maintaining a live signal accumulator in Redis that the feed reads immediately, without waiting for the DB job.

---

## 2. Three-Layer Architecture

```
┌─────────────────────────────────────────────────────┐
│              Module Session Taste                    │
│         Redis · per module · 2h inactivity TTL      │
│    Highest responsiveness · Most volatile            │
└──────────────────────┬──────────────────────────────┘
                       │ sync on feed request
                       │ (shared dimensions only)
┌──────────────────────▼──────────────────────────────┐
│              Global Session Taste                    │
│         Redis · cross-platform · 1 day TTL          │
│    Today's full-platform behavioural memory          │
└──────────────────────┬──────────────────────────────┘
                       │ nightly promotion at 3am IST
                       │ (gated: confidence + quality + events)
┌──────────────────────▼──────────────────────────────┐
│              Persistent Taste                        │
│         PostgreSQL · user_post_taste · permanent     │
│    Long-term user identity · evolves conservatively  │
└─────────────────────────────────────────────────────┘
```

**Rule: writes only flow downward. Module never writes directly to Persistent.**

---

## 3. Layer Responsibilities

### Module Session Taste

- **Scope:** Single module (Posts), single user, single active session
- **Purpose:** Immediate feed adaptation — learns what the user wants *right now* in this module
- **Volatility:** Highest — expires after 2 hours of inactivity
- **Dimensions held:** All three (category, commodity, author) — module-specific
- **Decay:** Continuous exponential decay (λ = 0.023, same as persistent)
- **Example behavior:** User switches from Rice to Cotton posts mid-session → commodity weights shift within the next feed call

### Global Session Taste

- **Scope:** All modules, single user, single day
- **Purpose:** Today's cross-platform behavioural memory — bridges multiple app opens and multiple modules within the same day
- **Volatility:** Medium — cleared nightly after promotion to persistent
- **Dimensions held:** Cross-platform only (commodity, location†, quantity†)
- **Decay:** Continuous exponential decay (λ = 0.023)
- **Example behavior:** Morning Rice posts + afternoon Rice news → Global commodity:Rice accumulates from both modules → evening feed strongly Rice-oriented

† Location and quantity are placeholder keys in Global. They are stored but zero-weighted until the modules that generate those signals are built.

### Persistent Taste

- **Scope:** Permanent, per user
- **Purpose:** Long-term user identity — who this user is as a trader over weeks and months
- **Volatility:** Lowest — updated only via the nightly promotion job, never by real-time events
- **Dimensions held:** All (category, commodity, author)
- **Decay:** Continuous (λ = 0.023, ~30-day half-life)
- **Example behavior:** User consistently saves Cotton deals over 3 months → persistent commodity:Cotton score grows slowly to reflect their identity as a Cotton trader

---

## 4. What Each Layer Holds (Dimensions)

| Dimension | Module Session | Global Session | Persistent |
|---|:---:|:---:|:---:|
| Category (deal_req, market_update, discussion, knowledge) | ✓ | ✗ | ✓ |
| Commodity (Rice, Cotton, Sugar) | ✓ | ✓ | ✓ |
| Author affinity | ✓ | ✗ | ✓ |
| Location (future) | ✗ | ✓ placeholder | ✓ |
| Quantity (future) | ✗ | ✓ placeholder | ✓ |

**Insight:** Global holds only cross-platform dimensions because those are the only signals that are meaningful *across* modules. A post category like "deal_req" means nothing to the News module. Commodity (Rice/Cotton/Sugar) is relevant everywhere. This is why category and author stay in Module only, while commodity flows up to Global.

---

## 5. Redis Data Structures

### Module Session — `session:post:{profile_id}`

Type: **Hash**  
TTL: **2 hours** from last event (EXPIRE resets on every write)

```
Field pattern:   {dim_prefix}:{dim_key}:{field}

cat:{category}:pos      Float   accumulated positive taste score
cat:{category}:neg      Float   accumulated negative taste score
cat:{category}:conf     Float   accumulated confidence score
cat:{category}:cnt      Int     event count
cat:{category}:ts       Int     unix timestamp of last event (for decay)

com:{commodity_id}:pos  Float
com:{commodity_id}:neg  Float
com:{commodity_id}:conf Float
com:{commodity_id}:cnt  Int
com:{commodity_id}:ts   Int

aut:{author_id}:pos     Float
aut:{author_id}:neg     Float
aut:{author_id}:conf    Float
aut:{author_id}:cnt     Int
aut:{author_id}:ts      Int

_total_events           Int     total events across all dimensions (for influence weight)
_session_start          Int     unix timestamp when session began
_last_event_at          Int     unix timestamp of most recent event
_last_synced_ts         Int     unix timestamp of last module→global sync
```

**Dim prefix mapping:**
- `cat` → dimension_type = "category"
- `com` → dimension_type = "commodity"
- `aut` → dimension_type = "author"

**Write operations use atomic Redis commands:**
```
HINCRBYFLOAT  session:post:{pid}  cat:deal_req:pos   +2.0
HINCRBYFLOAT  session:post:{pid}  cat:deal_req:conf  +0.5
HINCRBY       session:post:{pid}  cat:deal_req:cnt   +1
HSET          session:post:{pid}  cat:deal_req:ts    {now_unix}
HINCRBY       session:post:{pid}  _total_events      +1
EXPIRE        session:post:{pid}  7200              ← resets 2h inactivity timer
```

---

### Global Session — `session:global:{profile_id}`

Type: **Hash**  
TTL: until 3am IST nightly flush (set explicitly, not rolling)

```
commodity:{id}:pos    Float   accumulated positive commodity score (all modules combined)
commodity:{id}:neg    Float
commodity:{id}:conf   Float
commodity:{id}:cnt    Int
commodity:{id}:ts     Int

location:{key}:pos    Float   placeholder (zero-weighted until activated)
quantity:{key}:pos    Float   placeholder (zero-weighted until activated)

_total_events         Int     total events contributed from all modules today
_day                  Int     YYYYMMDD — detects day rollover
_last_synced_at       Int     unix timestamp of last sync from any module
```

**Note:** Commodity is the only active cross-platform dimension in Phase 1. All location/quantity fields exist in the schema but contribute zero influence until future modules populate them.

---

## 6. Signal Weights — Taste and Confidence

Every interaction produces two deltas: a **taste delta** (what to update in the score) and a **confidence delta** (how certain are we about this signal).

| Interaction | Taste (pos) | Taste (neg) | Confidence | Dimensions written |
|---|---:|---:|---:|---|
| Impression | +0.1 | — | +0 | category, commodity |
| View (first open) | +0 | — | +0.1 | category (conf only) |
| Dwell bounce (<2s) | — | +0.5 | +0 | category, commodity (neg) |
| Dwell short (2–8s) | +0.5 | — | +0.2 | category, commodity |
| Dwell medium (8–30s) | +2.0 | — | +0.5 | category, commodity, author† |
| Dwell long (≥30s) | +3.5 | — | +1.0 | category, commodity, author† |
| Open read more | +1.5 | — | +0.3 | category, commodity |
| Open carousel | +1.0 | — | +0.2 | category, commodity |
| Open comments | +1.5 | — | +0.3 | category, commodity |
| Link click | +2.0 | — | +0.5 | category, commodity, author† |
| Like | +3.0 | — | +2.0 | category, commodity, author† |
| Save | +5.0 | — | +4.0 | category, commodity, author† |
| Comment | +4.0 | — | +5.0 | category, commodity, author† |
| Share | +4.0 | — | +6.0 | category, commodity, author† |
| Revisit (2nd open) | +6.0 | — | +4.0 | category, commodity, author† |

† Author dimension is written only when `taste_delta >= 2.0` (AUTHOR_TASTE_MIN_DELTA) AND `author != viewer`.

**Insight — Why confidence ≠ taste:** Taste measures *how much* a signal shifts the score. Confidence measures *how certain we are* this signal represents real intent. A comment (+4.0 taste, +5.0 confidence) provides more certainty than a long dwell (+3.5 taste, +1.0 confidence) because commenting is an explicit, effortful act. The system separates these because the confidence score governs when session signals are *trusted enough* to influence the feed — not just how much they shift it.

**Insight — Why bounce has confidence = 0:** A bounce (< 2 seconds) tells us the user didn't want to see that post right now, but it tells us nothing reliable about their long-term preferences. They might have been distracted. Confidence zero means a bounce never pushes the session closer to "trusted" — it only applies the negative taste signal without increasing the system's certainty about this dimension.

---

## 7. Confidence Thresholds

Confidence thresholds determine when a session dimension is trusted enough to influence the feed. Thresholds scale with the strength of the existing persistent score — established preferences are harder to shift than weak ones.

### Category Threshold — Flat

```
CATEGORY_CONFIDENCE_THRESHOLD = 10  (same for all 4 categories)
```

Equal threshold for all categories because they compete proportionally via log1p normalization. There is no reason deal_req should be harder to shift than knowledge.

### Commodity Threshold — Scales With Persistent Score

**Module Session:**
```
module_commodity_threshold(persistent_score) = 8 × (1 + persistent_score / 50)
```

| Persistent commodity score | Module threshold | Confidence needed for 0.70 gate |
|---|---|---|
| 0 (new user, no history) | 8.0 | 5.6 — one save + one dwell_long |
| 20 (occasional trader) | 11.2 | 7.8 — two likes + some dwell |
| 50 (regular trader) | 16.0 | 11.2 — two saves + one like |
| 100 (active trader) | 24.0 | 16.8 — four saves |
| 200 (dominant commodity) | 48.0 | 33.6 — ~8 saves — sustained session |

**Global Session:**
```
global_commodity_threshold(persistent_score) = 12 × (1 + persistent_score / 100)
```

| Persistent commodity score | Global threshold | Notes |
|---|---|---|
| 0 | 12.0 | Harder than module — global needs more cross-platform evidence |
| 50 | 18.0 | Still harder than module |
| 100 | 24.0 | Equal to module |
| 200 | 36.0 | Easier than module — heavy cross-platform users can still shift |

**Insight — Why threshold scales with persistent score:** A Rice trader with 200 saves over 3 months has a strong, validated preference. One session of Cotton activity should not meaningfully shift their commodity weights. A new user with no history can shift quickly because there's nothing established to protect. The scaling formula ensures the system becomes progressively more stable as the user's identity solidifies.

### Author Threshold

```
AUTHOR_SESSION_CONFIDENCE_THRESHOLD = 6
```

Lower than commodity and category because author affinity is binary per-author (you either care about this person or you don't) and a save or revisit provides strong immediate evidence.

---

## 8. Author — Three States

| State | Source | Reranker multiplier |
|---|---|---|
| Followed author | Social graph (`user_connections`) | Fixed **1.5×** |
| Not followed, persistent history | `user_post_taste` dimension_type='author' | **[1.0 – 1.2×]** via log1p |
| Not followed, session-only (new interest) | Module Session author dimension | **[1.0 – 1.1×]** via session confidence |

Session author state is temporary. A user who saves 2 posts from an unknown author in this session gets a provisional 1.1× boost for that session. After the global promotion job runs nightly, this may move into persistent history (State 2). Without promotion, it disappears.

**Insight:** The lower ceiling for session-only authors (1.1× vs 1.2×) encodes provisional trust. The system has seen this interaction once, in one session. It should respond, but not as strongly as a months-long pattern.

---

## 9. Influence Weights — How Layers Merge

Session influence is **additive at the weight preparation level**, before the reranker. The reranker formula itself does not change.

```
g_influence = 0.15 × min(global_conf / global_threshold, 1.0)
m_influence = 0.31 × min(module_conf / module_threshold, 1.0)
p_influence = 1.0 - g_influence - m_influence

merged_weight[key] = (
    p_influence × persistent[key]
  + g_influence × global[key]
  + m_influence × module[key]
)
```

| State | Persistent | Global | Module |
|---|---|---|---|
| Session just started | 100% | 0% | 0% |
| Module at 50% confidence | ~85% | 0% | ~15% |
| Module at 100% confidence | ~54% | ~15% | ~31% |
| Maximum session influence | **54% min** | **15% max** | **31% max** |

**Persistent never drops below 54%.** Global never exceeds 15%. Module never exceeds 31%.

### Per-Dimension Read Sources

| Dimension | Persistent | Global | Module |
|---|:---:|:---:|:---:|
| Category | ✓ | ✗ | ✓ |
| Commodity | ✓ | ✓ | ✓ |
| Author | ✓ | ✗ | ✓ |

Commodity gets all three layers. Category and Author get two layers each.

### Where In The Code

```python
# In get_recommended_posts() — BEFORE calling _rerank()

# Current (persistent only):
cat_weights       = taste_service.get_taste_weights(db, pid, "category", role_id)
commodity_weights = taste_service.get_taste_weights(db, pid, "commodity")
author_weights    = taste_service.get_taste_weights(db, pid, "author")

# With session taste (same interface, richer input):
cat_weights       = session_service.merge_category_weights(db, pid, role_id)
commodity_weights = session_service.merge_commodity_weights(db, pid)
author_weights    = session_service.merge_author_weights(db, pid)

# _rerank() call is UNCHANGED
scored = _rerank(db, pool, cat_weights, commodity_weights, author_weights, followed_ids)
```

**Insight — Why additive, not multiplicative:** The six factors in `_rerank()` are already multiplicative. Adding session taste as a seventh multiplicative factor would make it exponentially powerful — a strong session signal combined with a strong persistent preference would compound. Additive blending at the weight level means session taste *replaces* a portion of persistent taste rather than multiplying on top of it. The total influence is bounded and predictable.

---

## 10. Decay

Both Redis layers decay continuously using the same formula as persistent taste:

```
decayed_score = raw_score × exp(-λ × seconds_since_last_event / 86400)
λ = 0.023   (≈ 30-day half-life)
```

Decay is applied **at read time** (when the feed is requested), not at write time. This is consistent with how persistent taste works and avoids the need to rewrite Redis on a schedule.

**Within a 2-hour module session**, the maximum decay is:
```
exp(-0.023 × 2/24) = exp(-0.00192) ≈ 0.998
```
Less than 0.2% decay over the full module session. Practically invisible within a session — the decay only becomes meaningful across days (in Global) and weeks (in Persistent).

**Insight — Why decay in Redis at all:** Global Session lives for a full day. A burst of Rice activity at 8am should have *less* influence on the 10pm feed than Rice activity at 9pm. Continuous decay ensures recency within the day — not just binary "happened today / didn't happen today."

---

## 11. Session Boundaries and Triggers

### Module Session

| Event | Action |
|---|---|
| Batch events received (`POST /posts/interactions/batch`) | Write signals to module session Redis. Reset 2h TTL. |
| Feed requested (`GET /posts/recommendation/feed`) | Sync module → global (commodity delta only). Read all three layers. Merge weights. Serve feed. |
| 2 hours of inactivity | Redis TTL expires. Module session is lost. Next batch event starts a fresh module session. |
| Redis restart | Module session lost. Acceptable — user was likely inactive. |

### Global Session

| Event | Action |
|---|---|
| Module → Global sync (on feed request) | Compute delta since `_last_synced_ts`. Push commodity delta to global. Update `_last_synced_at`. |
| Day rollover detected (request arrives with `_day ≠ today`) | Trigger promotion job immediately (if not yet run). Clear global. Begin new day. |
| Nightly promotion job (3am IST) | Read global. Check three gates per dimension. Write qualifying deltas to persistent. Clear global. |
| Redis restart | Global session may be partially lost (up to 5-min RDB snapshot interval). Acceptable — persistent taste still serves the feed. |

### Persistent Taste

| Event | Action |
|---|---|
| Like / save / comment / share / revisit | Synchronous write to `user_post_taste` (unchanged — existing behavior) |
| `run_taste_update_job` (every 12 hours) | Process unprocessed dwell events from `post_interaction_events` → `user_post_taste` (moved from 15 min — session Redis now handles real-time) |
| `run_global_persist_job` (daily 3am IST) | Global Session → Persistent Taste (new job) |
| `run_ignore_detection_job` (daily 3am IST) | Unchanged — repeated-ignore negative signals |

---

## 12. Nightly Promotion — Global → Persistent

Runs at 3am IST. Applied **per dimension independently** — one dimension can promote while another fails its gates.

### Three Gates (all must pass per dimension)

```
Gate 1 — Confidence Gate:
  min(dimension_conf_score / threshold, 1.0) >= 0.70
  → The accumulated confidence for this dimension must be ≥ 70% of its threshold
  → Ensures signal quality

Gate 2 — Quality Gate:
  sum(positive_taste_deltas for this dimension today) >= 20
  → The accumulated weighted taste score must be substantial
  → Ensures engagement magnitude (not just occasional signals)

Gate 3 — Event Gate:
  count(events with confidence_delta > 0 for this dimension) >= 10
  → At least 10 meaningful events (impressions and bounces excluded)
  → Ensures behavioral breadth, not just one-off bursts
```

**"Meaningful event" definition:** Any event with confidence_delta > 0. This excludes impressions (conf=0) and bounces (conf=0). A dwell_short (conf=0.2) counts as 1 meaningful event.

### Gate Failure Examples

| Scenario | Gate 1 | Gate 2 | Gate 3 | Outcome |
|---|---|---|---|---|
| 4 saves in 2 minutes, then closes app | ✓ | ✓ (20) | ✗ (4 events) | No promotion |
| 15 impressions + 3 dwell_short | ✗ | ✗ (1.5) | ✗ (3) | No promotion |
| 10 dwell_medium + 2 likes | ✓ | ✓ (26) | ✓ (12) | Promote |
| 2 views + 1 like | ✗ | ✗ (3.1) | ✗ (3) | No promotion |

### Promotion Formula

```python
# Per dimension (applied only when all 3 gates pass):

global_delta = global_pos_score - (global_neg_score × 0.6)
persistent   += 0.15 × global_delta
```

**Only 15% of the global delta enters persistent.** This is the conservative evolution rate.

**Example — 3 months of daily Rice activity:**
```
Day 1:  global_delta=31.4  → persistent_rice += 4.71  → persistent=4.71
Day 7:  persistent ≈ 28.5  (with daily decay + daily promotion)
Day 14: persistent ≈ 47.8
Day 30: persistent ≈ 72.0  (medium-active user territory)
Day 90: persistent ≈ 110   (dominant commodity)
```

**Insight — Why 0.15 and not higher:** If the promotion factor were 0.5 or 1.0, a single unusually active day (user caught a viral Cotton deal thread) would permanently and significantly shift their identity. The user trades Rice primarily — one Cotton day should not make them a "Cotton trader" in the system. 0.15 means a single day contributes a meaningful but small increment. Identity changes over weeks, not days.

### Promotion Job Safety

```
Step 1: READ Global Session from Redis
Step 2: Apply three gates per dimension
Step 3: WRITE qualifying deltas to PostgreSQL   ← commit to DB first
Step 4: CLEAR Global Session in Redis           ← only after DB confirms
Step 5: SET promotion_flushed_at = today in DB  ← idempotency flag

If Redis crashes between Step 3 and Step 4:
  → DB has the data (safe)
  → Global Session still exists in Redis
  → Next run: idempotency flag prevents double-write, just clears Redis

If DB write fails in Step 3:
  → Redis is not cleared
  → Global Session preserved for retry
```

Write-then-clear is the inviolable order.

---

## 13. Redis Persistence Strategy

| Layer | Persistence | Rationale |
|---|---|---|
| Module Session | None (accept loss) | 2h TTL — volatile by design. Loss = fresh session on next interaction. Acceptable. |
| Global Session | **RDB snapshots every 5 minutes** | Up to 5 minutes of cross-module signals lost on restart. Persistent taste still serves feed. Acceptable. Full AOF is overkill for session data. |

### Failure Handling

```python
def get_taste_weights_for_feed(db, profile_id, role_id):
    try:
        module  = redis.hgetall(f"session:post:{profile_id}")
        global_ = redis.hgetall(f"session:global:{profile_id}")
        return merge_all_layers(db, profile_id, role_id, module, global_)
    except (RedisConnectionError, RedisTimeoutError):
        # Redis down → silent fallback to persistent only
        # No error thrown, no 503, user still gets a feed
        return taste_service.get_taste_weights(db, profile_id, "category", role_id), ...
```

Redis down = graceful degradation to persistent taste. The feed continues to work. It is not as responsive to the current session, but it is not broken.

---

## 14. Scheduler — All Jobs

| Job ID | Frequency | Function | Change from current |
|---|---|---|---|
| `posts.expiry` | Every 1 hour | Partition aging, soft-expire, hard-delete cold | Unchanged |
| `posts.popular` | Every 15 min | Recompute velocity-based popular pool | Unchanged |
| `posts.taste_update` | **Every 12 hours** | Process unprocessed dwell events → `user_post_taste` | **Moved from 15 min** — session Redis handles real-time |
| `posts.ignore_detect` | Daily 3am IST | Repeated-ignore negative signals → `user_post_taste` | Unchanged |
| `posts.global_persist` | **Daily 3am IST** | Global Session → Persistent Taste (three-gate promotion) | **New job** |

**Insight — Why the DB taste job moves from 15 min to 12 hours:** The 15-minute job existed to minimize the gap between behavior and taste update. Session taste closes that gap entirely for real-time signals. The DB job now becomes a durability mechanism — ensuring that events in `post_interaction_events` are eventually persisted even if Redis data is lost. 12 hours is frequent enough to ensure the nightly promotion job has accurate data, but infrequent enough to reduce DB write pressure by ~48×.

---

## 15. Complete Data Flow

### Batch Events (User Scrolls)

```
Client sends POST /posts/interactions/batch
         │
         ├─ Write to post_interaction_events (processed_at=NULL)  ← durable event log
         ├─ Write to session:post:{pid} (Redis)                    ← real-time session
         │    HINCRBYFLOAT cat:{category}:pos  +{taste_delta}
         │    HINCRBYFLOAT cat:{category}:conf +{conf_delta}
         │    HINCRBYFLOAT com:{commodity}:pos +{taste_delta}
         │    ...
         │    EXPIRE session:post:{pid} 7200                       ← reset inactivity timer
         └─ seen_posts UPSERT for dwell >= 3s                      ← immediate exclusion
```

### Feed Request

```
Client sends GET /posts/recommendation/feed
         │
         ├─ READ session:post:{pid}   (module session)
         ├─ Compute delta since _last_synced_ts
         ├─ WRITE delta to session:global:{pid}                    ← module → global sync
         │    HINCRBYFLOAT commodity:{id}:pos  +{delta}
         │    HSET _last_synced_at {now}
         │
         ├─ READ session:global:{pid} (global session)
         ├─ READ user_post_taste (DB)                              ← persistent taste
         │
         ├─ merge_category_weights(module, persistent)            ← 2 layers
         ├─ merge_commodity_weights(module, global, persistent)   ← 3 layers
         ├─ merge_author_weights(module, persistent)              ← 2 layers
         │
         └─ _rerank(db, pool, cat_w, com_w, aut_w, followed_ids) ← unchanged
```

### Nightly Persistence (3am IST)

```
run_global_persist_job()
         │
         ├─ READ session:global:{pid} for all active users
         ├─ For each dimension per user:
         │    ├─ Gate 1: conf_score / threshold >= 0.70?
         │    ├─ Gate 2: quality_score >= 20?
         │    ├─ Gate 3: meaningful_events >= 10?
         │    └─ If all pass:
         │         global_delta = pos_score - (neg_score × 0.6)
         │         UPDATE user_post_taste SET positive_score += 0.15 × global_delta
         │
         ├─ COMMIT to PostgreSQL
         └─ DELETE session:global:{pid} (clear for new day)
```

---

## 16. Decision Reference Table

| Parameter | Value | Source |
|---|---|---|
| Module session TTL | 2 hours inactivity | Finalized |
| Global session TTL | 1 day (cleared at 3am IST) | Finalized |
| Decay lambda (all layers) | 0.023 (~30-day half-life) | Existing constant |
| Decay application | At read time | Consistent with persistent layer |
| Category confidence threshold | 10 (flat, all categories) | Finalized |
| Module commodity threshold | `8 × (1 + persistent/50)` | Finalized |
| Global commodity threshold | `12 × (1 + persistent/100)` | Finalized |
| Author session threshold | 6 | Finalized |
| Module max influence | 0.31 | Finalized |
| Global max influence | 0.15 | Finalized |
| Persistent min influence | 0.54 | Derived (1 − 0.31 − 0.15) |
| Influence model | Additive at weight level | Finalized |
| Confidence gate | ≥ 0.70 | Finalized |
| Quality gate | ≥ 20 weighted taste score | Finalized |
| Event gate | ≥ 10 meaningful events (conf > 0) | Finalized |
| Promotion factor | 0.15 × global_delta | Finalized |
| Promotion applied | Per dimension independently | Finalized |
| Module → global sync trigger | On every feed request | Finalized |
| Persistent DB job frequency | Every 12 hours (from 15 min) | Finalized |
| Global persist job | Daily 3am IST | Finalized |
| Redis structure | Flat Hash with atomic fields | Finalized |
| Redis persistence (module) | None | Finalized |
| Redis persistence (global) | RDB every 5 min | Finalized |
| Redis failure handling | Silent fallback to persistent | Finalized |
| Author followed | 1.5× fixed | Existing, unchanged |
| Author persistent history | [1.0 – 1.2×] | Existing, unchanged |
| Author session-only | [1.0 – 1.1×] | New, lower ceiling |
| Location/quantity dimensions | Placeholder, zero-weighted | Phase 1 |
| Home feed module | Consumer of existing tastes, no own model | Future |
| Scalability | All future modules follow same lifecycle | Architecture principle |
