# Vanjiyaa Post System — Complete Flow Documentation

> Covers: Post Module · Post Recommendation Module · User Taste Profiling  
> Codebase state: 2026-06-18  
> Current model: persistent taste (no session taste / no Redis)  
> Purpose: Describe every step, every weight, and the reasoning behind every design decision.

---

## 1. System Philosophy

Vanjiyaa is an agri-trade network for traders, brokers, and exporters dealing in Rice, Cotton, and Sugar. The home feed must show each user posts that are genuinely relevant to their trade — not chronologically, not by popularity alone, but by a combination of what they trade, where they are, what role they play, and what they have already shown interest in.

Three problems the system solves:

**Problem 1 — Cold content discovery:** A newly published deal/req post by a Rice trader in Surat should immediately reach other Rice traders near Surat, even before any likes or comments accumulate. Pure popularity-based feeds fail new content.

**Problem 2 — Learned preference drift:** A Broker who spends most of their time reading Discussion posts should see more Discussions. A Trader who saves every deal/req should see more deals. The system must learn from behavior without requiring the user to configure anything.

**Problem 3 — Feed exhaustion and repetition:** A user scrolling through their feed must not see the same post twice within 30 days, and must get a fresh batch each time they reach the bottom. The system must handle infinite scroll without server-side session state.

These three problems map directly to the three modules:
- **Post Module** → what content exists and what interactions it receives
- **User Taste Profiling** → what the user has shown interest in
- **Recommendation Module** → matching content to preference, managing freshness and seen-state

---

## 2. The Post Module — Content Lifecycle

### 2.1 What a Post Is

A post is the atomic unit of content. Every post has:

- **Category** — the type of content (1=Market Update, 2=Knowledge, 3=Discussion, 4=Deal/Req)
- **Commodity** — what it's about (1=Rice, 2=Cotton, 3=Sugar)
- **Author** — the profile that published it, with a role (Trader/Broker/Exporter)
- **Location** — either the post's own lat/lon or the author's business location
- **Target roles** — optional restriction to specific roles (null = all roles can see it)
- **Engagement counters** — `like_count`, `comment_count`, `save_count`, `share_count`, `view_count` (denormalized on the posts row for fast reads)
- **Deal details** — only for category=4: commodity_quantity, price, grain_type

### 2.2 Post Lifecycle: From Creation to Feed

```
Author publishes post
        │
        ▼
INSERT INTO posts (category_id, commodity_id, title, caption, image_urls,
                   target_roles, lat/lon, ...)
        │
        ▼
post/service.py → rec_service.index_post()
        │
        ├── Compute 10-dim vector via build_post_vector()
        │       commodity[0:3]  one-hot for this post's commodity
        │       role[3:6]       multi-hot for target_roles (all-ones if unrestricted)
        │       geo[6:9]        3D unit-sphere Cartesian (cos(lat)×cos(lon), cos(lat)×sin(lon), sin(lat))
        │       qty[9]          commodity_quantity / 5000 for deal posts; 0 for others
        │
        ├── Compute expires_at = now + CATEGORY_EXPIRY_DAYS[category]
        │       market_update:  2 days   (time-sensitive price info)
        │       deal_req:       7 days   (trade offers stay relevant 1 week)
        │       discussion:    14 days   (community conversations age more slowly)
        │       knowledge:     90 days   (how-to content stays valid for months)
        │
        └── INSERT INTO post_embeddings
                post_id, vector, partition='hot', is_active=True,
                expires_at, category (denormalized), commodity_idx, created_at
```

**Why the vector is structured this way:**

The 10 dimensions encode everything that determines whether a post is relevant to a user. Commodity matching is the most important signal in an agri-trade network — a Cotton trader should not see Rice deals. Role matching ensures deal posts restricted to Exporters don't clutter a Trader's feed. Geo matching surfaces posts from nearby markets. Quantity matching helps connect traders who deal at compatible volumes.

**Why 3D Cartesian for geo instead of lat/lon directly:**

Cosine similarity works on dot products. Using raw lat/lon would create discontinuities near the international date line and poles, and the "closeness" would not scale linearly with distance. Converting to 3D Cartesian unit sphere coordinates means two nearby locations produce a high dot product regardless of where they are on the globe.

**Why the expiry varies by category:**

Market Update posts lose relevance within 48 hours — a price update from Monday is useless by Wednesday. Knowledge articles are valid for months. Setting different expiry durations prevents stale market updates from flooding the feed while ensuring valuable knowledge content stays discoverable.

### 2.3 Post Deletion and Closure

```
DELETE /posts/{id}     → rec_service.remove_post_index() → post_embeddings.is_active = False
POST /posts/{id}/close → same → is_active = False (soft — post still exists in DB)
POST /posts/{id}/close → reopen → rec_service.index_post() → is_active = True, partition = 'hot'
```

Setting `is_active = False` immediately removes the post from all ANN queries. The expiry job later handles cleanup.

### 2.4 The Five Explicit Interactions

These are synchronous user actions. Each one immediately updates taste and counters.

#### Like (`POST /posts/{id}/like`)

```
User taps Like
    │
    ├── Is there a post_likes row for (post_id, profile_id)?
    │
    ├── YES → Unlike path:
    │       DELETE FROM post_likes WHERE post_id=? AND profile_id=?
    │       UPDATE posts SET like_count = like_count - 1
    │       [No taste update on unlike — removing a like doesn't mean dislike]
    │
    └── NO → Like path:
            INSERT INTO post_likes (post_id, profile_id)
            UPDATE posts SET like_count = like_count + 1
            record_interaction(profile_id, category_id, "like", commodity_id, author_profile_id)
                → positive_delta = 3.0
                → writes user_taste_profiles (legacy)
                → writes user_post_taste: category += 3.0, commodity += 3.0, author += 3.0
```

**Why like = +3.0:** A like is a deliberate, low-effort positive signal. The user consciously tapped a button. It's stronger than passive dwell but weaker than saving (which signals intent to return) or commenting (which signals investment).

#### Save (`POST /posts/{id}/save`)

```
Same toggle structure as Like.
On save: record_interaction(..., "save", ...) → positive_delta = 5.0
```

**Why save = +5.0 (highest):** Saving is the highest-intent signal. The user is bookmarking the post to refer back to. In an agri-trade context, saving a deal means the user intends to act on it. This is fundamentally different from a passive scroll-past. No other action except revisit (+6.0) carries more weight, and revisit is only generated by the server on a second post-open.

#### Comment (`POST /posts/{id}/comments`)

```
record_interaction(..., "comment", ...) → positive_delta = 4.0
UPDATE posts SET comment_count = comment_count + 1
```

**Why comment = +4.0:** Writing a comment requires effort and explicit intent. It's stronger than a like (3.0) because the user typed something, but slightly below save (5.0) because commenting doesn't necessarily mean the user wants to transact.

#### Share (`POST /posts/{id}/share`)

```
record_interaction(..., "share", ...) → positive_delta = 4.0
UPDATE posts SET share_count = share_count + 1
[Non-unique — each share is a new post_shares row]
```

**Why share = +4.0:** Sharing means the user found the content valuable enough to forward. Equal to comment. Note: share is non-unique — a user can share the same post multiple times (e.g., to different people), and each share increments the counter and adds a new row.

#### View / Revisit (`GET /posts/{id}`)

```
First open:
    INSERT INTO post_views (post_id, profile_id)  [unique constraint]
    UPDATE posts SET view_count = view_count + 1
    INSERT INTO seen_posts (profile_id, post_id)  [excludes from future feed]
    [No taste update — viewing alone is too weak a signal]

Second open (duplicate view):
    IntegrityError on post_views INSERT
    → record_revisit_event()
        INSERT INTO post_interaction_events (event_type='revisit', processed_at=now)
        record_interaction(..., "revisit") → positive_delta = 6.0
        writes user_post_taste: category += 6.0, commodity += 6.0, author += 6.0
```

**Why revisit = +6.0 (strongest explicit signal):** If a user comes back to the same post a second time, it is an extremely high-confidence signal. In an agri-trade context, re-opening a deal means the user is seriously considering it. The first open is passive (they might have just tapped by accident), but the second open is deliberate.

**Why view alone doesn't update taste:** A single view is too ambiguous. The user might have accidentally tapped, or quickly scanned and moved on. Only revisit (confirmed second open) is strong enough to update taste.

### 2.5 The Interaction Signal Weight Table

```
Signal           Trigger              pos_delta   neg_delta   Why
────────────────────────────────────────────────────────────────────────────────
impression       scroll into view         0.1         0.0     Very weak — passive
dwell_bounce     < 2000 ms                0.0         0.5     User left quickly — negative
dwell_short      2000–8000 ms             0.5         0.0     Glanced, slight interest
dwell_medium     8000–30000 ms            2.0         0.0     Read it, meaningful engagement
dwell_long       ≥ 30000 ms               3.5         0.0     Strong engagement
open_read_more   tapped "read more"       1.5         0.0     Wanted the full content
open_carousel    swiped images            1.0         0.0     Looked at visuals
open_comments    opened comments          1.5         0.0     Curious about discussion
link_click       tapped source URL        2.0         0.0     Clicked external reference
like             tapped like              3.0         0.0     Deliberate positive
save             tapped save              5.0         0.0     Highest-intent positive
share            tapped share             4.0         0.0     Found worth sharing
comment          submitted comment        4.0         0.0     Engaged deeply
revisit          second open              6.0         0.0     Confirmed strong interest
```

**Why negative signal only for bounce:** We don't want to punish users for slow scrolling or accidentally pausing on a post. The only reliable negative signal is a very short dwell (< 2 seconds) — the user saw the post and immediately scrolled away. This is a strong "not interested" signal. All other events, even impression, are weakly positive or neutral.

**Why the dwell thresholds are where they are:**
- < 2000ms: user saw the thumbnail and rejected it
- 2000–8000ms: glanced at the caption, mild interest
- 8000–30000ms: read the full caption, looked at images — meaningful engagement
- ≥ 30000ms: spent significant time, possibly re-read or studied the content

---

## 3. The User Taste System — Learning Preferences

### 3.1 The Two Tables

The system maintains two parallel taste stores:

**`user_taste_profiles` (legacy)** — one flat row per user with integer category counters:
```
profile_id | market_update_count | deal_req_count | discussion_count | knowledge_count | total_events
```
Still receives writes from all interaction paths. No longer read by the reranker. Kept for audit/migration safety.

**`user_post_taste` (active)** — one row per (user, dimension, key):
```
(profile_id=7, dimension_type="category",  dimension_key="deal_req")     → pos=52.0, neg=0.0,  events=18
(profile_id=7, dimension_type="category",  dimension_key="market_update") → pos=14.0, neg=2.0,  events=9
(profile_id=7, dimension_type="commodity", dimension_key="1")             → pos=38.0, neg=0.5,  events=22
(profile_id=7, dimension_type="author",    dimension_key="22")            → pos=5.0,  neg=0.0,  events=2
```

**Why separate positive and negative scores:** They decay at the same rate but need to be weighted differently. Negative signals represent "I didn't want to see this type" and should discount the positive score, not erase it. The formula `net = decayed_pos - (neg × 0.6)` means: even if you bounced off a deal_req post twice, your strong history of saving deal_reqs still dominates.

**Why float instead of integer:** Integer counters (legacy) can't represent fractional signal weights like dwell_short (+0.5). Float columns allow all signal weights to be stored exactly without rounding at write time.

**Why the three dimensions (category, commodity, author):**
- **Category** — the most important signal. What type of post does this user engage with?
- **Commodity** — a user might trade both Rice and Cotton but engage much more with Rice content. The recommendation should reflect this.
- **Author** — if a user repeatedly saves posts from author X, author X's new posts should get a boost even if their vector similarity is mediocre.

### 3.2 The Three Write Paths

#### Write Path 1: Synchronous (like / save / comment / share / revisit)

```
User taps Like on post 101
    │
    ▼
service.record_interaction(db, profile_id=7, category_id=4, "like",
                            commodity_id=1, author_profile_id=22)
    │
    ├── derive_signal("like", None) → (pos=3.0, neg=0.0)
    │
    ├── LEGACY WRITE: user_taste_profiles
    │       find or create row for profile_id=7
    │       deal_req_count += 3    [int(3.0 + 0.5) = 3]
    │       total_events += 1
    │       db.commit()
    │
    ├── taste_service.update_taste(7, "category", "deal_req", +3.0, 0.0)
    │       pg_insert ON CONFLICT DO UPDATE  [atomic upsert]
    │
    ├── taste_service.update_taste(7, "commodity", "1", +3.0, 0.0)
    │
    └── if 22 != 7 AND 3.0 >= AUTHOR_TASTE_MIN_DELTA(2.0):
            taste_service.update_taste(7, "author", "22", +3.0, 0.0)
    │
    └── db.commit()   [all three upserts commit together]
```

**Timing: immediate.** The next feed call sees the updated weights.

**Why author only writes for signals ≥ 2.0:** An impression (+0.1) or dwell_short (+0.5) isn't strong enough to establish author affinity. If every scroll past an author's post created an author row, the author dimension would become noise. Only genuine engagement (like, save, comment, share, revisit, dwell_medium, dwell_long, link_click) should contribute to author taste.

**Why author skips self-interactions:** `author_profile_id != profile_id` guard. A user publishing their own post and then liking it shouldn't boost their affinity toward themselves.

#### Write Path 2: Asynchronous Dwell (every 15 minutes via scheduler)

Dwell, open_*, and link_click events go through the batch endpoint and land in `post_interaction_events` with `processed_at = NULL`. The taste update job processes them:

```
run_taste_update_job() fires every 15 minutes
    │
    ├── SELECT * FROM post_interaction_events
    │       WHERE event_type IN ('dwell','open_read_more','open_carousel',
    │                             'open_comments','link_click')
    │         AND processed_at IS NULL
    │       ORDER BY id
    │       LIMIT 500
    │
    ├── For each event: classify + accumulate into upt_deltas dict
    │       key = (profile_id, dimension_type, dimension_key)
    │       value = [pos_total, neg_total, event_count]
    │
    ├── For dwell events specifically:
    │       value_ms < 2000ms (bounce):
    │           upt_deltas[(pid, "category", cat)] += [0, 0.5, 1]
    │           upt_deltas[(pid, "commodity", str(cid))] += [0, 0.5, 1]
    │           [No legacy write — user_taste_profiles has no negative column]
    │           [No author write — bounces don't affect author affinity]
    │
    │       value_ms 2000–8000ms (short, +0.5):
    │           upt_deltas[(pid, "category", cat)] += [0.5, 0, 1]
    │           upt_deltas[(pid, "commodity", str(cid))] += [0.5, 0, 1]
    │           [No author write — 0.5 < AUTHOR_TASTE_MIN_DELTA(2.0)]
    │
    │       value_ms 8000–30000ms (medium, +2.0):
    │           upt_deltas += category, commodity, author
    │
    │       value_ms >= 30000ms (long, +3.5):
    │           upt_deltas += category, commodity, author
    │
    ├── open_read_more (+1.5), open_carousel (+1.0), open_comments (+1.5):
    │       upt_deltas += category, commodity
    │       [No author write — all below 2.0 threshold]
    │
    ├── link_click (+2.0):
    │       upt_deltas += category, commodity, author
    │
    ├── Apply all accumulated deltas:
    │       For legacy (positive events only):
    │           UPDATE user_taste_profiles SET {col} += int_delta, total_events += 1
    │       For user_post_taste:
    │           taste_service.update_taste() for each accumulated (key)
    │
    └── UPDATE post_interaction_events SET processed_at = now WHERE id IN (...)
        db.commit()
```

**Why batch instead of per-event:** Dwell events arrive continuously during scrolling. If each dwell immediately triggered a DB write, the taste tables would see O(impressions) writes — far too high for a mobile app with heavy scrolling. Batching 15 minutes of events into one DB operation reduces write pressure by ~50x.

**Why 500 events per run:** A safety limit to prevent a single job run from locking the table for too long. If more than 500 unprocessed events exist, the next run (15 minutes later) will continue.

#### Write Path 3: Ignore Detection (daily at 03:00 IST)

```
run_ignore_detection_job() fires daily at 03:00 IST
    │
    ├── SELECT profile_id, post_id FROM post_interaction_events
    │       GROUP BY profile_id, post_id
    │       HAVING
    │           SUM(impression events) >= 5         ← REPEATED_IGNORE_THRESHOLD
    │           AND SUM(dwell/open/revisit events) = 0   ← zero engagement
    │           AND SUM(unprocessed impressions) > 0     ← not already actioned
    │       LIMIT 500
    │
    ├── For each (profile_id, post_id) pair:
    │       taste_service.update_taste(pid, "category", cat, pos=0.0, neg=1.0)
    │       taste_service.update_taste(pid, "commodity", str(cid), pos=0.0, neg=1.0)
    │       [No author negative — ignoring a post type ≠ disliking the author]
    │
    └── UPDATE post_interaction_events SET processed_at = now
            WHERE event_type = 'impression'
              AND processed_at IS NULL
              AND (profile_id, post_id) IN (detected pairs)
```

**Why 5 impressions:** One or two scroll-pasts could be accidental. Five impressions with zero engagement is a reliable signal of "I keep seeing this type of post and I consistently ignore it."

**Why only category and commodity, not author:** Repeatedly ignoring a post type is a preference signal, not a judgment about the author. The user might ignore all knowledge posts regardless of who writes them, or all Cotton-related content because they don't trade Cotton.

**Why mark impressions processed:** The same (profile_id, post_id) pair must only generate one negative delta. The `processed_at IS NULL` guard in the HAVING clause ensures each pair is actioned exactly once. Without this, the same pair would re-trigger on the next daily run indefinitely.

### 3.3 Reading Taste — `get_taste_weights()`

This is called three times at the start of every feed request.

```python
cat_weights       = taste_service.get_taste_weights(db, profile_id, "category", role_id)
commodity_weights = taste_service.get_taste_weights(db, profile_id, "commodity")
author_weights    = taste_service.get_taste_weights(db, profile_id, "author")
```

**Step-by-step processing inside `get_taste_weights()`:**

```
Step 1 — Query rows
    SELECT * FROM user_post_taste
    WHERE profile_id = ? AND dimension_type = ?

    If no rows AND dimension = "category":
        return role defaults (cold-start fallback)
        DEFAULT_TASTE[role_id]:
            Trader(1):   {deal_req:100, market_update:80, discussion:20, knowledge:20}
            Broker(2):   {deal_req:100, market_update:60, discussion:50, knowledge:30}
            Exporter(3): {deal_req:60,  market_update:100, knowledge:50, discussion:20}
        [Reasoning: before any data, use the role's typical behavior as a prior]

    If no rows AND dimension ≠ "category":
        return {}   [no multiplier applied]

Step 2 — Apply exponential decay to each row
    days_since = (now - row.last_event_at).total_seconds() / 86400
    decayed_pos = row.positive_score × exp(-0.023 × days_since)

    TASTE_DECAY_LAMBDA = 0.023
    Half-life = ln(2) / 0.023 ≈ 30.1 days

    After 30 days:  score × 0.501   (50% remains)
    After 60 days:  score × 0.251   (25% remains)
    After 90 days:  score × 0.126   (12% remains)

    [Reasoning: tastes drift over time. A trader who used to save Cotton deals
     heavily but switched to Rice should see their Cotton taste fade within a
     few months. Exponential decay with a 30-day half-life achieves this without
     ever requiring an explicit "reset taste" operation.]

Step 3 — Apply negative discount
    net = decayed_pos - (row.negative_score × 0.6)
    net = max(net, 0.05)    [floor — no dimension ever reaches zero weight]

    _NEG_DISCOUNT = 0.6: negatives discount positives but never override them
    _SCORE_FLOOR = 0.05:  every category always has a minimum chance to appear

    [Reasoning: if a user bounced off 3 Market Update posts but saved 20, the
     net score is still strongly positive. The floor prevents complete suppression
     — even a category the user rarely engages with should occasionally appear.]

Step 4 — Confidence blend (category dimension only)
    total_events = sum(row.event_count for all rows)

    if total_events < TASTE_BOOTSTRAP_EVENTS (20):
        confidence = total_events / 20
        for each category:
            score = confidence × learned_score + (1 - confidence) × role_default

    [Reasoning: with only 3 interactions, the learned taste is unreliable.
     A user who happened to like 2 discussion posts in their first session
     should not immediately see a feed full of discussions — their actual
     role preferences should dominate until we have 20+ signals.
     The blend interpolates linearly between the role prior and learned data.]
```

**Worked example — taste transition:**

New Trader (role_id=1), 3 likes on deal/req posts:

```
After 3 likes on deal_req:
user_post_taste has: {deal_req: pos=9.0, events=3}
get_taste_weights("category", role_id=1):

  Step 1: One row — deal_req=9.0, no decay (just happened)
  Step 3: net = 9.0 - 0 = 9.0
  Step 4: total_events=3 < 20, confidence=0.15
          deal_req:      0.15×9.0  + 0.85×100 = 1.35 + 85.0  = 86.35
          market_update: 0.15×0.05 + 0.85×80  = 0.0075+68.0  = 68.01
          discussion:    0.15×0.05 + 0.85×20  = 0.0075+17.0  = 17.01
          knowledge:     0.15×0.05 + 0.85×20  = 0.0075+17.0  = 17.01

After 20 likes on deal_req (confidence=1.0):
  deal_req:      1.0×60.0 + 0.0×100 = 60.0
  market_update: 1.0×0.05 + 0.0×80  = 0.05   ← never engaged
  discussion:    1.0×0.05 + 0.0×20  = 0.05   ← never engaged
  knowledge:     1.0×0.05 + 0.0×20  = 0.05
  [Learned data now fully dominates]
```

---

## 4. The Recommendation Pipeline — Feed Request Lifecycle

Every call to `GET /posts/recommendation/feed?limit=25` runs through these phases in order. No state is carried between calls — the pipeline recomputes everything from the current DB state.

### 4.1 Phase 1 — Context Loading (7 DB queries)

```
SELECT Profile + Business + Commodities     [1 query with selectinload]
    → role_id, quantity_min, quantity_max
    → business.latitude, business.longitude
    → list of commodity_ids the user trades

SELECT UserEmbedding                        [1 query]
    → post_feed_vector (10-dim pre-built vector)
    → falls back to build_user_feed_vector() if NULL

SELECT user_post_taste WHERE dimension_type='category'    [1 query]
SELECT user_post_taste WHERE dimension_type='commodity'   [1 query]
SELECT user_post_taste WHERE dimension_type='author'      [1 query]
    → decayed, confidence-blended weights for reranking

SELECT UserConnection WHERE follower_id = user           [1 query]
    → set of followed user UUIDs for the social boost

SELECT SeenPost WHERE profile_id=? AND seen_at >= now-30d [1 query]
    → exclusion set: post IDs not to return
```

### 4.2 Phase 2 — User Vector Construction

The user vector is what gets compared against every post vector in the ANN index.

```python
# Pre-built path (preferred)
user_vec = parse(emb_row.post_feed_vector)

# Fallback: compute from profile
user_vec = build_user_feed_vector(
    commodity_ids=[1, 3],   # Rice and Sugar
    role_id=1,              # Trader
    lat=21.17, lon=72.83,   # Surat
    commodity_quantity=125, # avg of (50+200)/2
)
```

**Vector layout:**
```
Position  Meaning                         Construction
────────  ─────────────────────────────   ─────────────────────────────────────
0         Cotton component               averaged multi-hot of user's commodities
1         Rice component                   e.g. [Rice, Sugar] trader: [0, 0.5, 0.5]
2         Sugar component
3         Trader component               single-hot for user's role
4         Broker component                 Trader → [1, 0, 0]
5         Exporter component
6         Geo X = cos(lat)×cos(lon)      3D Cartesian from user's business location
7         Geo Y = cos(lat)×cos(lon)
8         Geo Z = sin(lat)
9         Quantity norm = avg_qty/5000   user's typical trade size
```

**Why averaged multi-hot for commodity:** A user who trades both Rice and Sugar equally should match Rice posts and Sugar posts equally. A pure one-hot for the "primary" commodity would miss half their relevant content.

### 4.3 Phase 3 — Candidate Retrieval

The goal is to assemble a pool of ~100–150 candidate posts. These are not yet the final feed — they are candidates for scoring and ranking.

#### Hot Partition (always queried)

```sql
SELECT post_id, category, vector
FROM post_embeddings
WHERE partition = 'hot'        -- posts 0–72 hours old
  AND is_active = true
  AND post_id NOT IN (seen_ids)
ORDER BY vector <=> CAST(:user_vec AS vector)   -- HNSW cosine distance
LIMIT 150
```

`<=>` is pgvector's cosine distance operator. The HNSW index makes this approximately O(log N) instead of O(N).

For each returned embedding:
```python
score = weighted_cosine_similarity(user_vec, post_vec)
# applies FEED_WEIGHTS before cosine: [3,3,3, 2,2,2, 1.5,1.5,1.5, 1.0]
pool.append({"post_id": ..., "category": ..., "vec_score": score})
pool_exclude.add(post_id)
```

**Why compute exact similarity after ANN retrieval:** The HNSW index uses raw cosine distance (unweighted). The retrieval gives approximate neighbors. The exact `weighted_cosine_similarity()` is computed in Python afterward to get the true score with dimension-specific weights applied.

**Why FEED_WEIGHTS = [3, 3, 3, 2, 2, 2, 1.5, 1.5, 1.5, 1.0]:**
```
Commodity dims (0-2): weight 3.0   ← most important — commodity mismatch is a hard reject
Role dims (3-5):      weight 2.0   ← important — Exporters don't want Trader-only posts
Geo dims (6-8):       weight 1.5   ← relevant — nearby markets preferred but not required
Quantity dim (9):     weight 1.0   ← weakest — quantity is a soft preference signal
```

A post about Rice targeting all roles, published in Surat, will score very high for a Rice trader in Surat. A post about Cotton targeting Exporters only will score near zero for a Trader, even if geo and quantity match perfectly — the commodity and role mismatch dominates.

#### Warm and Cold Partitions (fallback only)

```
If pool size < MIN_POOL_SIZE (80):
    Query warm partition (posts 72–120 hours old, deal_req/knowledge/discussion only)
    → LIMIT = 150 - current pool size

If still < 80:
    Query cold partition (posts 120–720 hours old, knowledge/discussion only)
    → LIMIT = 150 - current pool size
```

**Why Market Update posts don't exist in warm/cold:** Market updates become stale after 48 hours. By the time a Market Update enters "warm" (3+ days old), it's no longer valid information. The expiry job sets `is_active=False` on Market Updates at their 2-day `expires_at`.

**Why not always query warm and cold:** The hot partition covers 72 hours of posts. In an active network, this is usually more than enough to fill an 80-post pool. Querying warm and cold only on fallback avoids unnecessary ANN scans.

#### Popular Posts (always injected, regardless of pool size)

```python
popular = db.query(PopularPost)
    .filter(commodity_idx IN user_commodity_idxs, is_active=True)
    .order_by(velocity_score.desc())
    .limit(30)

# Each popular post enters with a fixed vec_score = 0.5
pool.extend([{"post_id": r.post_id, "category": r.category, "vec_score": 0.5}])
```

**Why popular posts bypass the ANN:** A highly viral post about Rice prices might have a very different geographical or role profile from this specific user. The ANN might rank it low due to vector mismatch. But a post with 200 saves in 2 hours deserves to surface in most feeds regardless — its engagement signal overrides the similarity concern.

**Why fixed vec_score of 0.5:** Popular posts didn't come from the ANN, so there's no similarity score for them. 0.5 is a neutral starting score — above threshold enough to survive reranking, but not so high that a popular post with weak taste fit outranks a highly relevant post.

**Velocity formula:** `(saves×3 + comments×2 + likes) / (hours+1)^1.5`

The weight hierarchy (saves > comments > likes) mirrors the signal weight table — saves represent the highest engagement intent. The `(hours+1)^1.5` denominator ages down the score super-linearly: a post with 100 engagement at age 2h is much more "viral" than the same count at age 50h. The +1 prevents division by zero for brand-new posts.

#### Fresh Post Guarantee (always injected)

```python
fresh = _ensure_fresh_in_pool(
    viewer_role_id=profile.role_id,
    commodity_idxs=user_commodity_idxs,
    exclude_ids=pool_exclude,
    user_vec=user_vec,
    limit=5,  # FRESH_SLOTS
)
```

```sql
SELECT pe.post_id, pe.category, pe.vector, p.target_roles
FROM post_embeddings pe JOIN posts p ON p.id = pe.post_id
WHERE pe.is_active = true
  AND p.created_at >= now - 4 hours    -- FRESH_INJECT_HOURS
  AND pe.commodity_idx IN (user_commodities)
  AND p.is_public = true
ORDER BY p.created_at DESC
LIMIT 15   -- fetch 3× to allow for role filtering
```

For each candidate:
- Check `target_roles` — skip if post is restricted to a role the viewer doesn't have
- Compute exact `weighted_cosine_similarity()` — no ANN approximation
- Add to pool if accepted, stop when 5 collected

**Why this guarantee exists:** The HNSW index was built from all active posts. When 200+ hot posts exist, the ANN only returns the top-150 by similarity. A post published 30 minutes ago might be exactly what this user needs, but its vector might rank 170th out of 200+ — below the cut. The fresh inject bypasses the ANN entirely for posts younger than 4 hours, ensuring new content always gets a chance to surface.

**Why 4 hours:** A new post published at 8am should be visible by noon. 4 hours guarantees that posts published within the last 4 hours are always injected regardless of their ANN rank.

**Pool state after all retrieval:** ~100–185 candidates, each represented as:
```python
{"post_id": int, "category": str, "vec_score": float}
```

---

### 4.4 Phase 4 — Reranking

This is the core of the recommendation system. Every candidate in the pool gets a final score computed from 6 multiplicative factors.

**Why multiplicative, not additive:**

The 6 factors represent different dimensions of quality. Each one is a multiplier that asks: "given the base similarity, how much should this specific signal scale it up or down?"

With additive scoring, a post could get a high final score by being mediocre on every dimension. With multiplicative scoring, a post must do reasonably well on most dimensions to score high. Specifically: a post that is completely wrong on commodity (vec_score near 0) gets a near-zero final score regardless of how fresh, engaging, or taste-matched it is. This is the correct behavior — commodity mismatch should be a near-disqualifier.

#### Setup: Bulk Load Candidates

```python
posts   = {p.id: p for p in db.query(Post).filter(Post.id.in_(all_pool_ids)).all()}
authors = {p.id: p for p in db.query(Profile).filter(Profile.id.in_(all_author_ids)).all()}
```

One bulk query for posts, one for authors. This avoids N+1 queries inside the scoring loop.

#### Factor 1 — Vector Similarity (`vec_score`)

Already computed during retrieval via `weighted_cosine_similarity()`.

```
Range: [0.0, ~0.95]
Popular posts: fixed 0.5 (no similarity computed)
```

This is the baseline relevance: how closely does this post's content profile match this user's profile?

#### Factor 2 — Category Taste Weight

```python
def _category_weight(cat_weights, category):
    total = sum(math.log1p(v) for v in cat_weights.values())
    return math.log1p(cat_weights.get(category, 0.05)) / total
```

**Example:**
```
cat_weights = {deal_req: 86.35, market_update: 68.01, discussion: 17.01, knowledge: 17.01}

log1p(86.35) = 4.459
log1p(68.01) = 4.222
log1p(17.01) = 2.888
log1p(17.01) = 2.888
total = 14.457

weight(deal_req)      = 4.459 / 14.457 = 0.308
weight(market_update) = 4.222 / 14.457 = 0.292
weight(discussion)    = 2.888 / 14.457 = 0.200
weight(knowledge)     = 2.888 / 14.457 = 0.200
```

**Why log1p and not raw scores:**

Raw scores would make this ratio extreme. If deal_req=86 and knowledge=17, raw normalization gives deal_req a 5× advantage. log1p(86)/log1p(17) ≈ 4.46/2.89 ≈ 1.5× advantage. The log compression prevents any single category from completely monopolizing the feed while still reflecting the user's preference ordering. Knowledge posts still have 0.20 weight — they appear in the feed, just less frequently than deals.

**Why normalized to sum to 1.0:** The category weight is a proportional allocation. Summing to 1 means it can be interpreted as "what fraction of the feed should be this category for this user?"

#### Factor 3 — Commodity Multiplier

```python
def _commodity_multiplier(commodity_weights, commodity_id):
    score = commodity_weights.get(str(commodity_id), 0.0)
    if score <= 0:
        return 1.0
    max_score = max(commodity_weights.values())
    return 1.0 + 0.3 * min(score / max(max_score, 0.05), 1.0)
```

**Range: [1.0, 1.3]**

**Example:**
```
User trades Rice heavily, Cotton occasionally.
commodity_weights = {"1": 28.0, "2": 4.0}   (Rice=28, Cotton=4)

For a Rice (commodity_id=1) post:
  score = 28.0, max = 28.0
  multiplier = 1.0 + 0.3 × (28/28) = 1.30×

For a Cotton (commodity_id=2) post:
  score = 4.0, max = 28.0
  multiplier = 1.0 + 0.3 × (4/28) = 1.0 + 0.3×0.143 = 1.043×

For a Sugar post (never interacted with):
  score = 0.0 → return 1.0  (no boost, no penalty)
```

**Why not a penalty below 1.0:** The ANN vector similarity already handles the "wrong commodity" case. A Sugar post shown to a Rice+Cotton trader would have a low vec_score from the commodity dimension. The commodity multiplier is an affinity amplifier, not a disqualifier.

**Why max 1.3:** A 30% boost for the user's most-engaged commodity is meaningful without overwhelming the other factors. The goal is to surface more of what the user interacts with, not to exclusively serve one commodity.

#### Factor 4 — Engagement Quality

```python
raw_eng = saves×3 + comments×2 + likes
engagement = min(math.log1p(raw_eng) / 6.9, 1.0)
factor = (1 + engagement)
# 6.9 ≈ log1p(1000) — normalizer: ~1000 weighted engagement units = engagement score 1.0
```

**Range: [1.0, 2.0]**

**Examples:**
```
Brand new post (0 engagement):       (1 + 0) = 1.00×
saves=5, comments=3, likes=20:       raw=41  → log1p(41)/6.9 = 0.54 → 1.54×
saves=50, comments=20, likes=200:    raw=390 → log1p(390)/6.9 = 0.86 → 1.86×
saves=200, comments=50, likes=500:   raw=1100→ log1p(1100)/6.9 ≈ 1.0  → 2.00×
```

**Why saves×3 + comments×2 + likes×1:** Same reasoning as signal weights — each action type represents different levels of intent. This is the post-level engagement metric (how engaging is the post to everyone), not the user-level taste signal (what does this specific user prefer). Both use the same action hierarchy.

**Why log1p normalization:** Without log compression, viral posts with thousands of engagements would completely dominate new posts. log1p(1000)/log1p(10) ≈ 6.9/2.4 ≈ 2.9 — a post with 1000 engagement gets only 2.9× the factor of a post with 10 engagement, not 100×. This preserves diversity between established and emerging content.

**Why capped at 1.0 (factor max 2.0):** A post cannot score more than 2× its similarity purely from engagement. This ensures that a post with perfect engagement but wrong commodity can't outscore a perfectly relevant new post.

#### Factor 5 — Freshness Boost

```python
def _freshness(created_at):
    age_h = hours_since_creation
    return 1.0 + 0.4 × math.exp(-age_h / 8.0)
    # FRESH_BOOST_PEAK = 0.4, FRESH_DECAY_TAU = 8.0 hours
```

**Range: [1.0, 1.4]**

```
Post age    Freshness multiplier   Reasoning
─────────   ───────────────────    ─────────────────────────────────────────
0h (new)    1.40×                  Just published — maximum boost
2h          1.31×                  Very recent
4h          1.24×                  Same day, still very fresh
8h          1.15×                  Roughly half the peak boost remains
12h         1.09×                  Still slightly fresh
24h         1.02×                  Nearly no boost
48h         1.00×                  Functionally expired freshness boost
```

**Why this formula (exponential decay with τ=8h):**
The boost should be concentrated in the first few hours when a post is truly "new news." By 24 hours, the freshness advantage should be minimal — a 1-day-old post should compete on its merits, not its age. The exponential decay with τ=8h achieves this: half the boost is gone in about 5.5 hours (half-life = τ × ln2 = 8 × 0.693 ≈ 5.5h), negligible by 24h.

**Why max 1.4 (not 2.0 or 3.0):** Freshness should give new content a chance but not dominate quality. A brand-new post with zero engagement and mediocre similarity should not outrank a 12-hour-old post that has 50 saves. The 40% ceiling keeps freshness meaningful without making it a trump card.

#### Factor 6 — Social / Author Affinity

```python
if author_user_id in followed_user_ids:
    social = 1.5   # fixed boost for followed authors

else:
    author_score = author_weights.get(str(post.profile_id), 0.0)
    social = get_author_affinity(author_score)
    # = 1.0 + 0.2 × min(log1p(score) / log1p(20.0), 1.0)
    # Range: [1.0, 1.2]
```

**For followed authors: 1.5× fixed**

Following someone on Vanjiyaa is an explicit high-confidence signal. The user has decided they want to see this person's content. A fixed 1.5× boost ensures followed users always have elevated visibility without depending on historical interaction data.

**For non-followed authors: [1.0, 1.2]**

```
Author score = 0  (never interacted):  1.00×
Author score = 5  (one save, some decay): 1.0 + 0.2 × (log1p(5)/log1p(20)) = 1.09×
Author score = 20 (saturation):         1.20×
Author score = 100 (well above sat):    1.20×  [capped]
```

**Why log1p compression for author affinity:** The first few interactions with an author should have meaningful impact. log1p means: going from 0 to 5 (first save) gives a bigger jump than going from 15 to 20 (near saturation). Early discovery of a good author should be rewarded.

**Why max 1.2 for non-followed:** Following = deliberate endorsement = 1.5×. Past interactions = passive history = max 1.2×. This gap between followed and merely-liked authors encourages users to follow content they genuinely want to track.

#### Final Score Assembly

```python
final = (
    vec_score                           # base similarity
    × _category_weight(cat, category)   # taste alignment
    × _commodity_multiplier(com, cid)   # commodity fit
    × (1 + engagement)                  # post quality signal
    × _freshness(created_at)            # recency boost
    × social                            # social/author signal
)
```

**Worked example — two competing posts:**

```
Post A: Deal/Req, Rice, 2h old, engagement=41, non-followed author (score=8)
Post B: Knowledge, Rice, 48h old, engagement=390, followed author

User context: Trader with heavy deal_req preference

Post A:
  vec_score     = 0.87
  category_w    = 0.308  (deal_req heavily preferred)
  commodity_m   = 1.30   (Rice is user's main commodity)
  engagement    = 1.54   (log1p(41)/6.9 = 0.54)
  freshness     = 1.31   (2h old)
  social        = 1.09   (author score=8 → 1.09×)
  final         = 0.87 × 0.308 × 1.30 × 1.54 × 1.31 × 1.09 = 0.767

Post B:
  vec_score     = 0.91   (slightly better match)
  category_w    = 0.200  (knowledge not preferred)
  commodity_m   = 1.30   (also Rice)
  engagement    = 1.86   (log1p(390)/6.9 = 0.86)
  freshness     = 1.00   (48h old — no boost)
  social        = 1.50   (followed author)
  final         = 0.91 × 0.200 × 1.30 × 1.86 × 1.00 × 1.50 = 0.659
```

**Post A wins (0.767 > 0.659)** despite lower vec_score, lower engagement, and a non-followed author. Category alignment (0.308 vs 0.200) and freshness (1.31 vs 1.00) are the deciding factors. This is the correct behavior: a Trader gets a new deal/req post ahead of an old knowledge post, even if the knowledge post has higher raw quality.

All candidates are sorted descending by `final_score`.

---

### 4.5 Phase 5 — Diversity Filter

```python
def _apply_diversity(scored, limit=25):
    cat_counts    = {}   # MAX_PER_CATEGORY = 8
    author_counts = {}   # MAX_PER_AUTHOR   = 3

    for item in scored:   # already sorted by final_score DESC
        if cat_counts.get(item["category"], 0) >= 8:     continue  # skip
        if author_counts.get(item["author_id"],  0) >= 3: continue  # skip
        cat_counts[item["category"]] += 1
        author_counts[item["author_id"]] += 1
        result.append(item)
        if len(result) >= 25: break
```

**Why diversity filtering:** Without this, the feed could theoretically contain all 25 posts from a single author who happens to post prolifically and score well. Or all 25 could be deal/req posts for a Trader who strongly prefers them. Either scenario makes the feed feel like a channel, not a curated timeline.

**Why 8 per category (not 4 or 5):** The feed has 25 posts and 4 categories. If a user strongly prefers one category, it should be able to dominate — up to about a third of the feed. 8/25 = 32%. Capping at 4 would frustrate users with strong preferences; no cap would create mono-category feeds.

**Why 3 per author:** A user following a very active author should see some of their posts, but not a quarter of their feed. 3/25 = 12% per author max. This also prevents the feed from being dominated by a single viral post creator.

**Key behavior:** Higher-scoring posts are accepted first. If author X has 10 posts in the scored list, the top 3 by final_score are accepted; the other 7 are skipped. The filter never reorders — it only prunes.

---

### 4.6 Phase 6 — Feed Card Construction

```python
# Batch queries — not per-post
liked_ids  = {PostLike.post_id for posts in viewer's likes in this feed}
saved_ids  = {PostSave.post_id for posts in viewer's saves in this feed}
authors    = {Profile by id for all author_ids in this feed}
```

Each `FeedPostCard` contains:
- Post content: id, title, caption, image_urls, source_url, category_id, commodity_id
- Post counters: like_count, comment_count, save_count, share_count, view_count
- Post geo: location_name (post.location_name OR "city, state" from author business)
- Post state: is_liked, is_saved (viewer-specific)
- Author: name, role string, company, avatar_url, is_user_verified, is_business_verified, author_user_id (UUID for the Follow button)
- is_following: true if this author is followed by the viewer
- Deal details: grain_type, grain_size, quantity, price, is_closed (if category=4)
- time_elapsed: human-readable age ("3 hours ago", "2 days ago")

**Why is_following is returned:** The frontend needs to know whether to show a "Follow" or "Following" button on the card without making a separate API call.

**Response:**
```json
{
  "posts": [...25 FeedPostCards...],
  "has_more": true
}
```

`has_more = len(posts) >= limit` — if the diversity filter produced fewer than 25 posts, the pool is exhausted.

---

## 5. The Seen Post System — Infinite Scroll

### 5.1 How Posts Get Marked Seen

**Path 1: Batch endpoint — dwell ≥ 3 seconds**

```python
# process_interaction_batch()
if event.event_type == "dwell" and value_ms >= 3000:
    seen_post_ids.append(event.post_id)

# Bulk upsert after processing all events:
INSERT INTO seen_posts (profile_id, post_id, seen_at)
SELECT :profile_id, unnest(:post_ids), :seen_at
ON CONFLICT (profile_id, post_id) DO NOTHING
```

**Path 2: Post detail open — GET /posts/{id}**

```python
# get_post() → rec_service.record_seen()
INSERT INTO seen_posts (profile_id=?, post_id=?, seen_at=now)
# try/except IntegrityError — silently ignored if already seen
```

### 5.2 The Exclusion Window

```python
cutoff = now - timedelta(days=30)
seen_ids = {r.post_id for r in
    db.query(SeenPost.post_id)
    .filter(profile_id==?, seen_at >= cutoff)
    .all()}
```

30-day window. A post seen 31+ days ago becomes eligible again.

**Why 30 days (not indefinite):** The agri-trade market operates in cycles. A deal/req from 6 weeks ago might have closed but a similar new one appeared. Allowing posts to resurface after 30 days means users don't permanently lose content they might want to revisit, and the exclusion table doesn't grow indefinitely.

### 5.3 How Infinite Scroll Works

```
Session 1:
  GET /feed → returns posts A, B, C... Y (25 posts)
  User scrolls, sends dwell events for A, B, C (≥ 3s each)
  seen_posts: {A, B, C}

  GET /feed → returns posts Z, AA, BB... (A, B, C excluded)
  User sends dwell for Z, AA
  seen_posts: {A, B, C, Z, AA}

  GET /feed → returns next batch...
  → has_more: false  (pool exhausted for current seen set)

Session 2 (next day):
  GET /feed → new posts published since yesterday appear
            → posts seen 31+ days ago also reappear
```

**Key property:** The system is stateless. The server doesn't remember which posts it delivered to you. It only knows what you've seen. Two users with identical profiles get identical feeds unless their seen sets differ.

---

## 6. The Post Embedding Partition System

### 6.1 Why Partitions Exist

The HNSW index contains every active post. Without partitions, a query for "top 150 posts" would compete across thousands of embeddings, and old low-traffic posts would permanently rank high if they happened to match a user's vector well.

Partitions enforce temporal relevance. The hot partition only contains posts from the last 72 hours. When the ANN scans the hot partition, every candidate is recent. Old posts don't compete with new ones in the primary scan.

### 6.2 Partition Rules

```
Post category     Hot (0–72h)    Warm (72–120h)    Cold (120–720h)    Expired (>expiry)
──────────────    ───────────    ──────────────    ───────────────    ─────────────────
market_update     ✓              ✗ (expires at 48h)  ✗                  is_active=False
deal_req          ✓              ✓                  ✗                  is_active=False
discussion        ✓              ✓                  ✓                  is_active=False
knowledge         ✓              ✓                  ✓                  is_active=False
```

Market Updates don't enter warm because they expire at 48 hours (`CATEGORY_EXPIRY_DAYS = 2`). The expiry job runs every hour and sets `is_active=False` for posts past their `expires_at`. By the time the partition job checks whether to move a Market Update to warm, it's already expired.

Deal/Req posts expire at 7 days and move hot→warm at 72h but don't enter cold — a deal that's been open for 5+ days is worth showing in warm but not keeping for 30 days.

Knowledge posts live longest — they can stay in cold for up to 720 hours (30 days) before hard deletion.

### 6.3 The Expiry Job (`run_expiry_job`, every 1 hour)

```
1. Soft-expire: post_embeddings WHERE is_active=True AND expires_at <= now
   → set is_active=False
   → also DELETE from popular_posts

2. Hot→Warm: post_embeddings WHERE partition='hot' AND created_at <= now-72h
             AND category IN ('deal_req','knowledge','discussion')
   → set partition='warm'

3. Warm→Cold: post_embeddings WHERE partition='warm' AND created_at <= now-120h
              AND category IN ('knowledge','discussion')
   → set partition='cold'

4. Hard delete: DELETE post_embeddings WHERE partition='cold' AND created_at <= now-720h
```

**Why hard delete cold posts instead of just soft-expiring them:** The `post_embeddings` table holds vector data. Keeping soft-deleted vectors forever would cause the table to grow indefinitely and slow down all future ANN scans (even though `is_active=False` excludes them from query results, the index itself gets larger). Hard deletion after 720h (30 days) keeps the cold partition bounded.

### 6.4 The Popular Posts Job (`run_popular_posts_sync`, every 15 minutes)

```
1. Get all active post_ids from post_embeddings
2. Query posts WHERE created_at >= now-30d AND id IN (active_ids)
3. For each post: velocity = (saves×3 + comments×2 + likes) / (hours+1)^1.5
4. Sort descending, take top 50 per commodity index
5. DELETE ALL from popular_posts
6. Bulk INSERT new rows
```

**Why delete-all + bulk-insert instead of UPDATE:** Velocity rankings change with every new engagement. A post that was #1 yesterday might be #8 today. Trying to maintain correct ordering via individual UPDATEs would require complex rank-shift logic. Delete-all + bulk-insert is atomically correct and simpler.

**Why every 15 minutes:** Popular posts can go viral within minutes. A deal post that gets 20 saves in 10 minutes should enter the popular pool quickly. 15-minute refresh is fast enough to capture viral behavior while not hammering the DB.

---

## 7. The Scheduler — Background Operations

All four jobs run inside the FastAPI process via APScheduler's `BackgroundScheduler(timezone="Asia/Kolkata")`.

```
Job ID                   Frequency       Function                          Purpose
────────────────────     ────────────    ──────────────────────────────    ──────────────────────────────────
posts.expiry             Every 1 hour    run_expiry_job()                  Age partitions, expire old posts
posts.popular            Every 15 min    run_popular_posts_sync()          Recompute velocity-based popular pool
posts.taste_update       Every 15 min    run_taste_update_job()            Process unprocessed dwell events → taste
posts.ignore_detect      Daily 03:00 IST run_ignore_detection_job()        Apply negative taste for repeated ignores
```

**Why ignore detection runs daily and not every 15 minutes:** Ignore detection is a GROUP BY aggregate over `post_interaction_events`. Running it every 15 minutes would scan the entire events table multiple times per hour. A user's "ignored" patterns don't need real-time updates — the daily job captures persistent ignore behavior without the query overhead.

**Why expiry runs every hour and not every 15 minutes:** Post expiry is not time-critical to the minute. A Market Update post that should expire at midnight is still acceptable to show until 1am if the job runs hourly. The cost of more frequent expiry runs doesn't justify the marginal improvement.

---

## 8. Complete System Interconnection

### 8.1 When a New Post Is Published

```
Author publishes → posts INSERT → post_embeddings INSERT (partition=hot, is_active=True)
                                       │
                                       ├─ Immediately visible in ANN hot scans
                                       ├─ Eligible for fresh inject (if < 4h old)
                                       ├─ NOT in popular_posts until next 15min job
                                       └─ NOT in any user's seen_posts until opened/dwelled
```

### 8.2 When a User Likes a Post

```
Like tap → post_likes INSERT → posts.like_count +1
                            → record_interaction("like")
                                → user_taste_profiles UPDATE (legacy)
                                → user_post_taste UPSERT (category, commodity, author)
                                → db.commit()

Next feed request (same session):
  get_taste_weights() reads the updated user_post_taste → higher category weight
  → that category's posts score slightly higher in reranking
```

### 8.3 When a User Scrolls (Dwell Events)

```
User scrolls → batch events accumulate on client → POST /posts/interactions/batch
                    │
                    ├─ post_interaction_events INSERT (processed_at=NULL)
                    ├─ seen_posts UPSERT for dwell >= 3s
                    └─ return immediately (no taste update yet)

                              ↓ (up to 15 minutes later)

run_taste_update_job() fires:
    reads unprocessed dwell events → classifies → accumulates → upserts taste
    marks processed_at = now

Next feed request (after job ran):
    get_taste_weights() reflects dwell signals
    seen_posts excludes all seen posts
```

### 8.4 The 15-Minute Gap Problem

This is the current system's primary limitation. Between when the user sends dwell events and when the taste update job processes them, there is a window of up to 15 minutes during which:

1. The user's taste profile does not reflect their session activity
2. The feed cannot adapt to what the user just read
3. A user who dwelled on 10 deal/req posts in a session and then requests a new feed will get recommendations based on their pre-session taste, not their current session behavior

This is not a correctness problem (taste is eventually updated), but a responsiveness problem. The user's experience of the feed improving as they engage is delayed.

**What remains accurate in real-time:**
- Like/save/comment/share update taste immediately
- Seen post exclusion is immediate (dwell >= 3s writes seen_posts synchronously in process_interaction_batch)
- Popular posts are refreshed every 15 minutes
- Post freshness is always computed live

**What is delayed by up to 15 minutes:**
- Dwell signal contribution to taste weights
- Open (read_more, carousel, comments) contribution to taste
- Link click contribution to taste

This gap is what session taste (the next implementation phase) is designed to close.

---

## 9. Data Flow Summary

### Feed Request: All Tables Touched

```
Read:
  profile             → role, quantity, commodity_ids
  business            → lat/lon
  user_embeddings     → post_feed_vector
  user_post_taste     → category/commodity/author weights (3 queries)
  user_connections    → followed user IDs
  seen_posts          → exclusion set (30-day window)
  post_embeddings     → ANN vector search (hot/warm/cold)
  popular_posts       → velocity-ranked fallback pool
  posts + post_embeddings → fresh inject (< 4h old)
  posts               → bulk load candidates for reranking
  profile (authors)   → author data for social factor + card building
  post_likes          → is_liked per card
  post_saves          → is_saved per card

No writes during the feed request path. Read-only.
```

### Interaction: Tables Written

```
like/save:           post_likes/post_saves, posts (counter), user_taste_profiles, user_post_taste
comment:             post_comments, posts (counter), user_taste_profiles, user_post_taste
share:               post_shares, posts (counter), user_taste_profiles, user_post_taste
open post:           post_views (first), posts.view_count (first), seen_posts
revisit:             post_interaction_events, user_taste_profiles, user_post_taste
batch events:        post_interaction_events (processed_at=NULL), seen_posts (dwell>=3s)
```

### Background Jobs: Tables Written

```
posts.expiry (1h):   post_embeddings (is_active, partition), popular_posts (DELETE expired)
posts.popular (15m): popular_posts (DELETE ALL + INSERT)
posts.taste (15m):   post_interaction_events (processed_at=now), user_taste_profiles, user_post_taste
posts.ignore (daily):post_interaction_events (processed_at=now), user_post_taste (negative)
```

---

## 10. Known Gap: Session Taste

The system as described above is complete and functional. The single architectural gap is the 15-minute latency between batch event submission and taste update.

**Current behavior:** User sends dwell events via batch endpoint → events sit in `post_interaction_events` with `processed_at=NULL` → taste update job processes them every 15 minutes → taste weights update → next feed reflects session behavior.

**Desired behavior:** User sends dwell events → next feed call immediately reflects session behavior without waiting for the job.

**Scope of the gap:** Only dwell and open/link events are affected. Explicit interactions (like/save/comment/share) already update taste synchronously. The gap specifically affects the passive behavioral signals that make up the majority of feed interactions.

**The session taste approach:** At feed request time, query `post_interaction_events WHERE profile_id=? AND processed_at IS NULL` to get the current session's unprocessed events. Classify and accumulate them using the same signal logic as the taste update job. Additively merge the resulting session scores into the persistent `user_post_taste` scores before normalization. The persistent scores and the session overlay are summed before entering `_category_weight()` — from the reranker's perspective, they're indistinguishable.

When the taste update job eventually runs, it processes those same events and writes them permanently into `user_post_taste`. The `processed_at` flag is set, and the next feed call no longer sees them in the session overlay — they're now in the persistent scores. The handoff is seamless: the same signal contributes to session taste until the job runs, then it moves into persistent taste automatically.

This change requires no new tables, no new migrations, no Redis, no new endpoints. It only requires:
1. A new `get_session_taste_overlay()` function in `taste_service.py`
2. A merge step in `get_recommended_posts()` before passing weights to `_rerank()`
