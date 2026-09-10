# Home Feed — Architecture

> Status: living design doc for the team. Describes what the feed module **is today**
> and what we are **going to build**. Implementation lands in phases (see §9).

---

## 1. Purpose

The home feed is a **single mixed stream** of four content types — posts, news,
group suggestions, connection suggestions — for the logged-in user.

The feed module is deliberately **thin**. It does not rank items itself. It answers
exactly one question of its own:

> **"How much of each content type do we show, and in what order?"**

Everything else — *which* posts, *which* people, *which* news — is delegated to the
owning module's recommender.

---

## 2. The one idea to internalise: two granularities of taste

Almost every design question collapses once you separate these two:

| Granularity | Question | Who owns it |
|---|---|---|
| **Item-taste** | *Which* posts / news / people? | Each source module |
| **Type-taste** | *How much* post vs news vs group vs connection? | **The feed** |

- **Item-taste** lives *inside* each module. Posts and News each have their own
  session item-taste (category / commodity / author / cluster drift) **plus** a
  persistent item-taste (`user_post_taste`, `UserClusterTaste`). Connections and
  Groups need **no** item-taste — a **seen-set + nearest-vector search** is enough.

- **Type-taste** is the feed's only intelligence. It is just **4 numbers** — the mix
  ratio for `post / news / group / connection` — fed to the mixer.

> ⚠️ **Hard rule:** the feed's taste store **never** copies a module's item-taste.
> A post dwell updates the *post* module's session item-taste (item-level) **and**
> bumps the feed's `post` **type** bucket (type-level). These are two separate writes
> to two separate stores. The feed only ever holds the type-level aggregate.

---

## 3. Current state (what is built today)

```
get_home_feed(db, user_id, profile_id, r, cursor)
│
├─ RECENCY LAYER (first load only)
│     └─ breaking news  →  news.get_news_feed().sections["right_now"]   → priority pins
│
├─ ITEM LAYER (delegated — 4 thin adapters in pipelines.py)
│     ├─ post        → post_recommendation_module.get_recommended_posts(db, profile_id, 20)
│     ├─ news        → news.get_news_feed(db, user_id)  → "for_you_today" section
│     ├─ connection  → connections.get_recommendations(db, r, user_id, page, 5)   (sync)
│     └─ group       → groups.get_group_suggestions(db, user_id, page, 5)
│
├─ TYPE-MIX LAYER
│     └─ STATIC weights  {post .45, news .25, group .15, connection .15}   ← placeholder
│
└─ mixer.mix_feed(candidates, weights, pins)   → weighted-random, max-consecutive cap ≤3
```

**What is intentionally NOT built yet:**
- No taste of any kind in the feed — the type-mix is a static dict.
- `POST /feed/engagement` is **acknowledge-only**; signals are not forwarded anywhere.
- Feed-owned Redis / session is **off** until the post & news session-taste pipelines ship.

This document describes the system **once those modules are done** and we layer the
feed's type-taste on top.

---

## 4. Target architecture (what we are going to build)

```
                         ┌──────────────────────────────────────────────┐
                         │                 FEED MODULE                   │
                         │                                              │
  app open / scroll ───► │  READ PATH                                   │
                         │   1. seed mix from GT (persistent type-taste)│
                         │   2. blend GST (session type-taste) in       │
                         │   3. call 4 recommenders (item layer)        │
                         │   4. prepend breaking-news pins (recency)    │
                         │   5. mix → page                              │
                         │                                              │
  engagement batch ────► │  WRITE PATH (dual-write per signal)          │
                         │   a. forward item-level → owning module      │
                         │   b. type-level → GST (Redis) + GT (DB)      │
                         └──────────────────────────────────────────────┘
```

Three layers, in priority order:

1. **Recency layer** — time-critical content that bypasses ranking. Today: breaking
   news pins (severity-gated, first load). Pure freshness, surfaced before the mix.
2. **Item layer** — delegate to each module's recommender (§3). Feed never ranks items.
3. **Type-mix layer** — the feed's type-taste decides the ratio, the mixer interleaves.

---

## 5. The taste system (type-taste only)

Two layers of the **same** thing — the 4-number type-mix — at different lifetimes:

| | **GST — Global Session Taste** | **GT — Global Taste** |
|---|---|---|
| Scope | Current session only | Lifetime of the user |
| Store | **Redis**, TTL ~2h | **DB** table |
| Key / row | `feed:gst:{profile_id}:{session_id}` | `(profile_id, content_type)` |
| Role | Drives the mix *right now* as the user scrolls | **Cold-start** seed when a session opens |
| Form | Raw signal counters (see §6) | Raw decayed counters (see §6) |

### 5.1 Lifecycle

```
APP OPEN (new session, GST empty)
    └─ seed mix from GT          →  GT empty (new user)?  → role-based defaults
SCROLLING
    └─ GST accumulates           →  final_mix = blend(GT, GST, f(items_seen))
ENGAGEMENT (every batch)
    └─ WRITE-THROUGH             →  update GST (hot)  AND  decayed-update GT (durable)
SESSION ENDS / GST TTL EXPIRES
    └─ nothing to do             →  GT already current (write-through), GST just vanishes
```

### 5.2 Why write-through (decision)

Redis TTL expiry is **passive** — it deletes the key, it cannot run code. So we do
**not** rely on "merge on expiry." Instead, **every engagement batch updates GST *and*
applies a small decayed update to GT in the same transaction.**

- GT is therefore **always current** — zero loss even if the session never formally ends.
- GST is purely a **fast, responsive cache** for the live session; if it vanishes, GT
  already holds the durable signal.

```
engagement signal
   ├─ GST  += signal                 (Redis, TTL 2h)   — responsive, this session
   └─ GT   += signal * decay_factor   (DB, persistent) — durable, cold-start seed
```

### 5.3 All four types drift (decision)

GST and GT track **all four** type buckets — including connection and group — even
though those two modules have no *item*-taste. The split:

- **Seen-set** (owned by connections/groups) → handles *"don't repeat a card."*
- **Type-weight** (feed's GST/GT) → handles *"how many of these cards to show."*

So if a user keeps engaging connection cards, the `connection` ratio rises; if they
ignore them, it falls — independent of which specific people get recommended.

---

## 6. Data model (raw signal counters — decision)

We store **raw counters**, not pre-normalized weights, and compute the mix at read
time. This matches the existing `session_taste.py` design, stays auditable, and lets us
retune the scoring formula without a migration.

### 6.1 GST — Redis value (per session)

`feed:gst:{profile_id}:{session_id}` → JSON, TTL 7200s:

```jsonc
{
  "post":       { "dwells": 0, "likes": 0, "saves": 0, "skips": 0, "total_dwell_ms": 0 },
  "news":       { "dwells": 0, "likes": 0, "saves": 0, "skips": 0, "total_dwell_ms": 0 },
  "group":      { "dwells": 0, "joins": 0, "dismisses": 0 },
  "connection": { "dwells": 0, "accepts": 0, "dismisses": 0 },
  "items_seen": 0
}
```

### 6.2 GT — DB table (persistent)

```
user_feed_type_taste
──────────────────────────────────────────────
profile_id       int          FK profile(id)
content_type     text         'post' | 'news' | 'group' | 'connection'
decayed_score    float        running, time-decayed positive signal
negative_score   float        running, time-decayed negative signal (skips/dismisses)
total_events     int          for confidence / bootstrap blend
last_updated     timestamptz  for query-time exponential decay
PRIMARY KEY (profile_id, content_type)
```

> Mirror the decay model already used by `user_post_taste` (≈30-day half-life,
> negatives discounted, floor so no type is fully suppressed) for consistency.

### 6.3 Signal → counter weights

Reuse the existing `ACTION_WEIGHTS` and `_observed_weights` shape from
`session_taste.py`:

```
save / join / accept   +5
share / comment        +4
like                   +3
dwell                  +2     (+30% bonus if avg_dwell > 6s)
skip / dismiss         −1
```

### 6.4 Weight computation (read time)

```
observed_weights(counters) =
    per type:  score = saves*5 + likes*3 + dwells*2 − skips        (avg-dwell bonus)
    normalize across the 4 types so they sum to 1.0

final_mix = blend_factor · GST_weights  +  (1 − blend_factor) · GT_weights

blend_factor(items_seen):
    items_seen < 8        → 0.0     (pure GT / cold start)
    else                  → min(0.8, 0.1 + (items_seen − 8) · 0.025)
```

- Early in a session → mix is dominated by **GT** (who the user *is*).
- As the session builds → mix shifts toward **GST** (who they are *right now*).
- Cap at **0.8** so a single session can never fully hijack the long-run mix.
- GT empty (brand-new user) → fall back to **role-based defaults**
  (`PAGE_LEVEL_DEFAULTS`).

---

## 7. Engagement flow (dual-write)

`POST /feed/engagement` is the **single ingestion point**. For each signal it does a
**dual-write** — one write per granularity:

```
signal { item_id, item_type, action, dwell_ms }
│
├─ (1) ITEM-LEVEL  → forward to the owning module
│        post        → POST /posts/interactions/batch   (impression/dwell/open_* )
│                      (like/save/comment/share already recorded by post endpoints)
│        news        → news.record_engagement(...)        (view/click/dwell/like/...)
│        connection  → connections.mark_recommendations_seen(...)   (dismiss → seen-set)
│        group       → groups seen-set / join signal
│
└─ (2) TYPE-LEVEL  → feed's own type-taste
         GST[item_type] += signal            (Redis)
         GT (profile_id, item_type) += signal · decay   (DB write-through)
```

Action-name translation is required — each module has its own vocabulary (post:
`impression/dwell/open_*`; news: `view/click/dwell/like/save/...`). The feed maps its
generic `ActionType` into each module's enum before forwarding.

> Active post engagement (like/save/comment/share) is **already** captured by the post
> module's own endpoints when the user taps them — the feed must **not** double-record
> those at the item level. It still counts them at the **type** level for the mix.

---

## 8. Component responsibilities (summary)

| Layer / file | Owns | Does NOT own |
|---|---|---|
| `pipelines.py` | Calling each recommender, mapping → `FeedItem` | Any ranking / scoring |
| `service.py` | Orchestration, recency pins, read/write of type-taste | Item ranking, item-taste |
| `mixer.py` | Weighted-random interleave, max-consecutive caps (≤3) | Choosing weights |
| GST (Redis) | Session type-mix counters | Item-taste, dedup |
| GT (DB) | Persistent type-mix counters, cold-start seed | Item-taste, dedup |
| Source modules | Item-taste, item ranking, **seen-sets** | The cross-type mix |

---

## 9. Phased rollout

- **Phase 0 — DONE.** Delegate item layer to the 4 recommenders + breaking-news
  recency pins. Static type-mix weights. Engagement endpoint acknowledge-only. Feed
  Redis off.
- **Phase 1 — Performance.** Run the 4 pipelines in parallel (per-thread DB sessions);
  point `REDIS_URL` at a reachable instance. (See PERF notes — sequential ≈ 9–10s,
  parallel ≈ max(posts) ≈ 5.5s.)
- **Phase 2 — GT (cold start).** Add `user_feed_type_taste` table + read path; replace
  the static weight dict with GT-derived weights (role defaults when empty).
- **Phase 3 — Engagement dual-write.** Wire `/feed/engagement` to forward item-level
  signals to each module **and** write-through to GT. (Prereq: post & news session
  item-taste pipelines complete.)
- **Phase 4 — GST (session drift).** Turn feed Redis on; add GST; blend GST↔GT via
  `blend_factor(items_seen)`. This is the existing `session_taste.compute_weights`
  logic, re-based onto GT instead of the static defaults.

---

## 10. Open items / notes

- **Pagination** is currently shallow: posts/news recommenders are not page-based, so
  `cursor.page_num` only advances connections/groups. Posts/news rely on their own
  seen-sets for cross-page novelty. Revisit if repeats become visible.
- **`documentation/feed_api.md`** still documents the old timestamp/offset cursor —
  the cursor is now just `{ "page_num": n }`. Needs updating.
- `priority.py` and `session_taste.py` are **orphaned** from Phase 0 (kept on disk).
  `session_taste.py` is the reference implementation we re-base in Phase 4; `priority.py`
  is superseded by the news `right_now` section.
- **Session identity:** GST is keyed by `session_id`; we will need to re-add a
  `session_id` to the cursor / a header when Phase 4 lands.
```
