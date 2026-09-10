# app_old → app_new Migration Ledger

**Rule 0 — the frontend is live against `app_old`. Every endpoint path, query param,
request body field and response JSON key in `app_new` must match `app_old` byte-for-byte
unless explicitly listed as an intentional change below.**

Ground truth is generated, never assumed:
```
sh _migration/run_gates.sh        # everything below, in one go
python3 _migration/extract_contracts.py app_old _migration/old.json
python3 _migration/extract_contracts.py app_new _migration/new.json
python3 _migration/diff_contracts.py          # endpoint set diff
python3 _migration/check_imports.py app_new   # unresolved intra-app imports
```

## Target architecture (pattern source: `modules/profile`, the one module already correct)

```
modules/<m>/
  domain/interfaces/repository.py   ABC, abstractmethods only
  domain/exceptions.py              module exceptions (no bare ValueError)
  data/models.py                    SQLAlchemy models
  data/repository.py                the ONLY place with db.query
  application/use_cases/*.py        take `repo` first arg, raise domain exceptions,
                                    never import from presentation/
  application/__init__.py           re-export service (routers import through it)
  presentation/router.py            _get_repo dep, try/except -> HTTPException, auth dep
  presentation/schemas.py           pydantic
```
Error mapping convention = per-endpoint `try/except` -> `HTTPException`, matching
`profile/presentation/router.py`. Not a global handler: `main.py` is not in this repo.

## Module status

| # | Module | eps old/new | Contract | Repo | Layers | Auth | Done |
|---|--------|------------|----------|------|--------|------|------|
| 1 | safety | 6/6 | exact | done | 4 | JWT | **YES** |
| 2 | deeplink | 3/3 | exact | done | 4 | n/a (public) | **YES** |
| 3 | verification | 5/5 | exact | done | 4 | JWT | **YES** |
| 4 | onboarding (old `auth`) | 4/4 | exact | done | 4 | JWT | **YES** |
| 5 | profile | 11/11 | **1 key fixed** | already ok | 4 | JWT | **YES** |
| 6 | chat | 15/15 | **2 restored** | ABC added | 4 | JWT | **YES** |
| 7 | connections | 19/19 live | exact | **deferred** | 4 | JWT | partial |
| 8 | post | 24/24 | exact | deferred | 4 | JWT | partial |
| 9 | groups | 32/32 | **exact** | deferred | 4 | JWT | partial |
| 10 | news (old `news_new`) | 16/16 | **exact URLs** | deferred | 4 | JWT | partial |
| 11 | home_feed (old `feed`) | 2/2 | exact | n/a | 4 | JWT | **YES** |
| 12 | core / shared / recommendation | — | | | | | |

## Cross-cutting defects found (verified in source, not docs)

| id | defect | status |
|----|--------|--------|
| X1 | 15 unresolved intra-app imports (boot blockers) | **0 — CLOSED** |
| X2 | `core/scheduler.py` shadowed by `core/scheduler/` package | **CLOSED** |
| X3 | `post/recommendation/jobs.py` shadowed by `jobs/` package | **CLOSED** |
| X4 | `core/redis_client.py` == `core/redis/client.py` (746 B identical) | **CLOSED** |
| X5 | 5 imports of deleted `app.modules.taste.*` | **CLOSED** — amplify.py ported |
| X6 | `ConvStatus` imported from `chat/domain/entities.py`; lives in `value_objects.py` | **CLOSED** |
| X7 | 72 zero-byte non-`__init__` .py stubs | **0 — CLOSED** |
| X8 | 15 of 17 `repository.py` empty -> 23 application files run `db.query` | **0 — CLOSED** |
| X9 | 11 application files import from `presentation/` | **0 — CLOSED** |
| X10 | `news/application/tasks.py:356` `log1p(negative)` -> ValueError, kills hourly job | **CLOSED** |
| X11 | `home_feed` lost `ThreadPoolExecutor` parallelism present in `app_old/modules/feed` | **CLOSED** |

## Log

### 2026-09-08 — module 1: safety + two boot-blocking import cycles

**Found by executing the code, not by reading it. Static analysis missed both cycles.**

* **X13 `profile` <-> `onboarding` circular import (P0, pre-existing).** Verified by
  `git stash`: original app_new **cannot import** `profile`, `onboarding`, `post` or
  `verification` at all. `profile/__init__` -> profile router -> `from app.modules.onboarding
  import create_session` -> onboarding router -> `from app.modules.profile import Profile`
  -> partially initialised package -> ImportError.
* **X14 `profile` <-> `post` circular import (P0, pre-existing)** via `_batch_feed_cards`.
  app_old avoided it with a function-local import (`app_old/modules/profile/service.py:429`);
  app_new hoisted it to module level.

Root cause for both: cross-module imports resolving through a package `__init__.py`, which
needs an *attribute* of a half-initialised package. Importing the defining submodule does not.

Fixes:
* `_migration/fix_crossmodule_imports.py --apply` rewrote **20 imports across 15 files** to
  concrete modules (name->module map taken from each package's own `__init__.py`, so the
  objects imported are identical).
* `profile/data/repository.py`: `_batch_feed_cards` made a function-local import, matching app_old.
* **Result: 11/11 module packages now import cleanly** (was 6/11). Gate: `test_imports.py`.

**Safety module — contract regressions found and reverted to app_old behaviour:**

| was in app_new | app_old (restored) |
|---|---|
| `POST /safety/{user_id}/block/{target_id}` — acting user from **URL**, **no auth dep at all** | `POST /safety/block/{target_id}`, actor from JWT. The app_new form was an **IDOR: anyone could block/report as anyone** |
| all 6 URLs carried a `{user_id}` segment | all 6 URLs restored exactly |
| `/blocked`, `/reports` had **no pagination** | `page` + `limit` query params restored (`ge=1`, `limit<=100`) |
| `list_blocked` returned `{user_id,total,blocked:[{blocked_id,blocked_at}]}` | `{blocked:[{blocked_id,blocked_at,name,avatar_url}],total,page,limit}` — Profile outerjoin restored |
| `list_my_reports` returned `{user_id,total,reports}` | `{reports,total,page,limit}` |
| 5 exceptions subclassed `ValueError`, router had **0** `except` -> every violation was **500** | `SafetyError` hierarchy in `domain/exceptions.py`, router maps 400/404/409 as app_old did |
| `application/__init__.py` empty -> `from ...application import service` was an ImportError | re-exports service |
| `data/repository.py` empty, SQL in application layer | `SafetyRepository` + `ISafetyRepository` ABC; **0** `db.query` outside `data/` |
| no `domain/` layer | `domain/{entities,exceptions,interfaces}`, 0 sqlalchemy/fastapi/pydantic imports |

Gates: `test_safety.py` PASS (6 routes, exact JSON keys, 400/404/409/422, 401 without token),
`test_imports.py` 11/11, contract diff shows **zero** safety differences.

### 2026-09-08 — module 2: deeplink

3 endpoints, contract now exact. Notably **two GAP_ANALYSIS.md claims are wrong** — verified
against the models, not the doc:

* *DL-2 "news table mismatch, all V1 article links 404"* — **not a bug.** app_old read
  `news_raw_articles` (`RawArticle`); app_new reads `news_articles` (`NewsArticle`). app_new's
  news pipeline writes `news_articles` and its feed hands the client those ids, so the deep
  link resolves the id the client actually holds. Self-consistent.
* *DL-3 "description fallback removed"* — **not a bug.** app_old's `description or api_summary`
  were two columns on `RawArticle`; `NewsArticle` consolidated them into one `summary` column.
  There is nothing to fall back to.

Real defects fixed:

| defect | fix |
|---|---|
| `application/__init__.py` empty -> `from ...application import service` was an ImportError; all 3 endpoints dead | re-exports service |
| `data/repository.py` empty, 4 queries in the application layer | `DeepLinkRepository` + `IDeepLinkRepository` ABC |
| no `domain/` layer, `DeepLinkNotFoundError` defined in application | `domain/{entities,exceptions,interfaces}` |
| `presentation/dependencies.py` empty | `get_deeplink_repo` |
| `__init__.py` empty | public API exported |

**One intentional deviation from app_old** (logged, not silent): `profile.business` is a 1:1
that may be absent; both trees dereferenced it unguarded, so `/share/user/{id}` raised
`AttributeError` -> **500** for any profile with no Business row. Now guarded -> 200 with
`description: null`. A 500 is not a contract, so this cannot break the client.

Gate: `test_deeplink.py` PASS — 3 routes, `share_text` asserted byte-for-byte (including the
`\n\n` gaps, the 120-char + "..." truncation, and the `" · "` join), `ok()` envelope,
404 bodies, malformed-UUID 404, non-int id 422.

### 2026-09-08 — module 3: verification

Router, request schemas and models were already contract-faithful (only import paths
differed). The work was layering, and one subtle behaviour that had to be preserved exactly.

**The rule that must not break:** a *provider rejection* (PAN invalid, GST inactive, IEC not
valid) is **not** an HTTP error in app_old. It is caught inside `verify_document`, stored as a
`status="error"` row, and the endpoint still returns **200** with `data.status == "error"`.
Only the pre-checks (KYB-before-KYC, wrong document for role) raise out to a 400. app_old
expressed both with a bare `ValueError`; that conflation is now explicit:
`DocumentRejectedError` (-> 200/error row) vs `VerificationError` subclasses (-> 400).

| defect | fix |
|---|---|
| router ran `db.query(Profile)` — SQL in the **presentation** layer | `repo.get_profile_by_user()` |
| `data/repository.py` empty; upsert + profile-flag SQL in application layer | `VerificationRepository` + ABC, upsert and flag still in **one** commit |
| `requests` / Surepass HTTP calls in the application layer | `data/adapters/surepass.py` behind `IDocumentVerifier` |
| no `domain/` layer; bare `ValueError` for two different meanings | `domain/{entities,exceptions,interfaces}` |
| `presentation/dependencies.py`, `application/__init__.py` empty | wired |

Gate: `test_verification.py` PASS — 5 routes, `ok()` envelope + exact messages, rejection
returns 200/`status=error`/`verified_at=null`/profile flag NOT set, KYB-before-KYC 400,
role rules 400 for both Trader-iec and Exporter-gst, aadhaar 501 that never reaches the
provider, 404 on all four endpoints when the profile is missing, status shape, 422.

Also added `_migration/run_gates.sh` — runs every gate in one command.

### 2026-09-08 — module 4: onboarding (app_old `auth`)

**GAP_ANALYSIS ON-4 ("3 empty placeholder use-cases ... 9 hrs") is wrong.**
`complete_profile.py`, `set_role.py`, `upload_document.py` were never features. Their own
comments read "No functions were extracted from service.py for this use case." app_old's
`auth` module has no such functions and nothing in app_new imports them. They were scaffolding
from the service.py split. **Deleted** — there is no missing behaviour and nothing to build.

| defect | fix |
|---|---|
| `verify_otp.py` ran `_firebase_app = _get_firebase_app()` at **import time** -> importing onboarding (and profile/post/verification transitively) raised FileNotFoundError with no `backend/service.json` | `data/adapters/firebase.py`, lazy + cached behind `IFirebaseVerifier` |
| router ran `db.query(User)` / `db.query(Profile)` — SQL in **presentation** | `repo.find_user_by_phone()`, `repo.find_profile_by_name()` |
| `data/repository.py`, `domain/interfaces/repository.py`, `presentation/dependencies.py` all empty; session SQL in the application layer | `OnboardingRepository` + `IOnboardingRepository` ABC, wired |
| 3 speculative placeholder files | deleted |

Gate: `test_onboarding.py` PASS — 4 routes; all three `firebase-verify` branches (brand-new /
exists-without-profile / returning) with exact messages; refresh-token **rotation** asserted
(new hash stored, differs from the presented token, refresh persisted only as a 64-char
SHA-256 and never equal to the raw token returned); 401 for bad token, missing phone claim,
unknown refresh, expired refresh (and that expiry deactivates the session), missing profile;
logout with a garbage token still returns 200 "Logged out." and revokes nothing;
`/auth/dev-token` 404s unless `DEBUG=true`; and an assertion that the Firebase app is **not**
constructed at import time.

### 2026-09-08 — module 5: profile

Profile already had a real repository (it was the pattern source), so this was a contract
audit plus two defects — one of which I caused.

**Frontend-visible break found: `ProfilePublicResponse.posts_count` had been renamed to
`page_posts_count`.** The value is identical in both trees (`len(posts)` — the current page,
not the user's total). app_new's author was right that the old name is misleading, but this is
a live response key. Renamed back to `posts_count`; the clarification is now a comment.
Caught by field-level diff of all 10 pydantic models, not by the endpoint diff.

**Regression I introduced in module 4, caught by the gates:** changing `create_session` to take
`IOnboardingRepository` broke its only external caller, `profile/presentation/router.py:87`,
which still passed `db`. A signature change is invisible to the static import checker — only
`test_imports.py` + the contract tests caught it. Fixed; profile now injects the onboarding
repository.

**X12 closed — the root cause of every import cycle so far.** Module `__init__.py` files
eagerly imported their router, so `from app.modules.profile.data.models import Profile`
pulled in the entire presentation layer. Fixing the profile caller re-created the cycle a
third time. Now `router` is exported **lazily via PEP 562 `__getattr__`** in profile,
onboarding, verification, deeplink and safety: model imports stay cheap, while
`from app.modules.X import router` still works. `test_imports.py` asserts both halves.

Also: `_get_repo` moved out of the router into `presentation/dependencies.py`; dead
`data/adapters/storage.py` stub deleted (nothing imported it).

Gate: `test_profile.py` PASS — 11 routes, **all 10 pydantic models compared field-by-field
against app_old**, `ok()` messages identical, error status codes identical, no SQL in the
application or presentation layers.

### 2026-09-08 — module 6: chat

**Two endpoints had been deleted outright and are restored:**

* `POST /chat/conversations` — get-or-create a DM. Without it **a user cannot start a DM at
  all.** The use case survived only in app_old; app_new's `ChatRepository` had no
  `get_or_create_dm` at all, so the method was ported too (idempotent, same query and the
  `{"id","status","created"}` response), along with the `OpenConversationRequest/Response`
  schemas which had also been dropped.
* `GET /chat/groups` — groups-only chat list. `repo.get_group_conversations()` still existed;
  the `GetGroupConversationsUseCase` wrapper had been lost. Ported to
  `application/use_cases/list_group_chats.py` with app_old's exact tz-stripping sort, and
  registered **before** `/chat/groups/{group_id}/messages` so routing order is right.

**Boot blocker X6 fixed at the root:** `ConvStatus` was imported from `domain/entities.py` in
5 places but lives in `domain/value_objects.py` as `ConversationStatus`. All 5 sites (chat x3,
connections, post) now import the real name; **zero `ConvStatus` references remain**.

**Dead code deleted:** `presentation/socket/manager.py` was a *byte-identical* copy of
`connection_manager.py` — a second, unregistered `sio` instance. Nothing imported it (all 4
call sites use `connection_manager`). Removed with the two empty `socket/` stubs.

**`IChatRepository` generated** from `ChatRepository`'s 18 public methods; the class now
declares it and has no unimplemented abstract methods.

**GAP_ANALYSIS CH-4 ("attachments never loaded, silently dropped") is wrong** — the new
repository queries `ChatAttachment` at `data/repository.py:370`, the same 3 usages as app_old.

Two blockers in *other* modules had to be fixed because chat's router imports them:
`groups/.../service.py` imported `ALLOWED_MEDIA_TYPES` from `create_group.py` (it is defined
in `manage_posts.py`, and was already imported correctly further down — the first import was
just bogus), and `create_group.py` imported `_KNOWN_COMMODITIES` from a non-existent
`connections.application.service` (it lives in `connections/.../search_users.py`).

Unresolved imports now **5** (from 15). Gate: `test_chat.py` PASS.

### 2026-09-08 — module 7: connections

**Runtime crash found — `ActionType` had lost 5 members.** app_new's enum dropped
`CONNECTION_FOLLOW`, `CONNECTION_MSG`, `GROUP_VIEW`, `GROUP_JOIN`, `GROUP_DISMISS`. Two of them
are called directly: `follow_user.py:105` and `send_message_request.py:93`. **Following a user
or sending a message request raised `AttributeError`.** No static check can see a missing enum
member. Restored all 5 with app_old's exact values, plus their 5 `SIGNAL_WEIGHTS` rows
(`connection_follow`/`connection_msg` = `(5.0, 0.0, 4.0)`, `group_dismiss` = `(0.0, 2.0, 0.0)`).
A gate now asserts every `ActionType` has a `SIGNAL_WEIGHTS` entry.

**`app_old/modules/taste/amplify.py` was never ported** — the source of the last 5 dangling
imports. Ported to `app/recommendation/amplify.py`, import paths only.
**Unresolved intra-app imports: 15 -> 0. X1 CLOSED.**

**Dead code deleted (verified unreferenced, and app_old had no equivalent):**
`recommendation/engine.py`, `recommendation/scoring.py`, `recommendation/session_taste/`,
`domain/interfaces/recommender.py`. GAP_ANALYSIS **CN-5/CN-6 are wrong** — recommendations are
served by `service.get_recommendations` + `recommendation/vectors.py`, which are real and intact.

**Dead legacy route modules deleted.** app_new had copied app_old's `connections/routes/`
as `routes_connections.py`, `routes_recommendations.py`, `routes_users.py` (20 route
decorators). Proof they are dead: app_old's originals import `app.modules.connections.db`,
which does not exist — if anything registered them app_old could not boot, and app_old works.
Nothing imports them in either tree. Removed, and the contract extractor now excludes
app_old's `connections/routes/` so the diff compares only the live surface (19 routes, exact).

**GAP_ANALYSIS CN-3 ("N+1 introduced in search_users") is wrong** — `joinedload(Profile.business)`
is missing from `search_users` in **both** trees, while `_fmt_profile` dereferences
`profile.business` per row. Pre-existing, not a regression. Fixed anyway: pure perf, no
contract change, and it matches what `_load_profiles_bulk`/`search_suggestions` already do.

**Deferred:** extracting `ConnectionsRepository` (31 `db.query` calls across 5 use-case files).
See the note at the end of this ledger on sequencing.

Gate: `test_connections.py` PASS.

### 2026-09-08 — module 8: groups, + the three shadowing/duplicate defects (X2, X3, X4)

**X2/X3 were silent boot blockers, proven by import, not by reading.** A package shadows a
module of the same name, so:

* `app.core.scheduler` resolved to the **empty** `core/scheduler/__init__.py`, not
  `core/scheduler.py`. `start()` and `scheduler` were unreachable — **every cron job was
  dead**, and `from app.core.scheduler import start` in main.py would be an ImportError.
  (`core/scheduler/instance.py` was a 71-line truncated copy of the 116-line module, missing
  `start()`/`stop()` and the global-taste promotion job.)
* `app.modules.post.recommendation.jobs` resolved to an **all-empty** `jobs/` package, so
  `run_expiry_job` / `run_popular_posts_sync` — which `core/scheduler.py` calls — did not exist.

Both shadowing packages deleted, plus `core/redis/` (X4: `client.py` byte-identical to
`core/redis_client.py`, `keys.py` empty, **nothing imported it** — the two `_client` globals
collapse to one). `test_scheduler.py` now asserts all **10** jobs register, including
`recommendation.global_taste_promotion` — which **GAP_ANALYSIS REC-9 claimed was missing**.

**C-3 confirmed and fixed:** app_old guarded its news jobs with `max_instances=1, coalesce=True`;
app_new had dropped them. Restored on `news.ingest`, `news.trending`, `news.taste`.

**Groups — app_new had removed the entire taste/amplify integration, not just an endpoint:**

| lost | restored |
|---|---|
| `POST /api/v1/groups/view` (+ `GroupViewSignal` schema + `record_group_view`) | endpoint back, 204, declared **above** `/{group_id}` so a UUID path can't swallow it |
| `get_group_suggestions` scored `compute_final_score(sim, act)` — no taste boost, suggestions were unpersonalised | `sim * commodity_boost(...)`, app_old's 0.75/0.25 blend |
| `join_group` took no `rc`/`actor_profile_id` and wrote no `GROUP_JOIN` signal | `_record()` on **both** paths (request-sent and joined), matching app_old |

This is why the `ActionType.GROUP_VIEW`/`GROUP_JOIN` members restored in module 7 were needed.

**Interval changes left alone but flagged** (not contract, may be deliberate tuning):
news pipeline 30 min -> 20 min, and `posts.taste_update` **12 h -> 15 min** (48x more frequent).

Gates: `test_groups.py`, `test_scheduler.py` PASS. Contract diff: groups **zero**.

### 2026-09-08 — module 9: news (the big one)

app_old `news_new` and app_new `news` are **different products**: GNews+Groq over
RawArticle/EnrichedArticle vs RSS+Gemini over NewsArticle. Every URL was renamed, so all 16
app_old endpoints were 404 for the live client. **All 16 now resolve.**

**N-1 fixed — and it is a new bug, not an inherited one.** `tasks.py:356` did
`log1p(raw_score)` where `raw_score` is a *signed* sum and `ACTION_WEIGHTS["skip"] = -1`. A user
who only skips reaches <= -1 and `math.log1p` raises `ValueError`, killing the hourly taste job
for **every user in the batch**. app_old only ever applied `log1p` to a positive count. Clamped
at 0 (net-negative interest = no taste). GAP_ANALYSIS called this a silent `-inf`; it is a hard
crash.

Restored in `presentation/compat_router.py` (delegating to app_new use cases — no invented
behaviour) and new use cases where app_new had nothing:

| app_old endpoint | how |
|---|---|
| `GET /news/articles/{id}`, `GET /news/feed/saved`, `POST /news/interactions/{like,save,share}/{id}` | aliases of existing app_new handlers |
| `GET /news/interactions/share-sheet/{id}` | `ChatRepository.get_share_recipients`, verbatim |
| `GET /news/trending` | **new** `use_cases/trending.py`. app_new kept the `NewsTrending` table and its 5-min recalc job but exposed **no read path** — trending was only an internal feed boost |
| `POST /news/interactions/batch` | **new** `use_cases/interaction_batch.py`, app_old's rules exactly: 200-event cap, 2 h staleness drop, unknown-article drop, 600 000 ms dwell cap, `{"accepted","dropped"}` |
| `GET /news/feed/{global,domestic}` | **new** `use_cases/geo_feeds.py`. `global` -> `scope=="global"`; `domestic` -> `scope in (local,state,national)` — exact, since app_old's `geo_category` was binary |
| `GET /news/feed/government` | **APPROXIMATION** — see below |
| `POST /news/interactions/send/{id}` | **new** `use_cases/send_article.py` — see below |
| `POST /news/admin/{ingest,enrich}`, `GET /news/admin/stats` | **new** `use_cases/admin.py`, mapped onto the RSS/Gemini pipeline |

**Chat schema regression found and fixed.** `POST /news/interactions/send/{id}` could not be
ported because app_new's chat `Message` model had **dropped the `article_id` column** and
`save_message` had dropped the parameter — a shared news article had nowhere to land. app_old
declares the column, so it exists in production. Restored (FK retargeted to `news_articles`),
`save_message` persists it again, and `IChatRepository` regenerated to match.

**The one place semantics are approximated, deliberately and flagged:**
`GET /news/feed/government`. app_old had an independent `is_government` boolean on
EnrichedArticle. `NewsArticle` has no such field. Mapped to `cluster_id == 1`
("Policy & Regulation"), the nearest concept in the new taxonomy. **To make this exact,
`NewsArticle` needs an `is_government` column and the Gemini classifier must populate it.**
`/news/admin/ingest` likewise accepts app_old's GNews `query`/`country` and reports them back
as ignored rather than silently swallowing them, because a fixed RSS list has no such concept.

Gate: `test_news.py` PASS — all 16 URLs resolve, log1p clamp verified against the raising
input, batch validation rules, geo mapping, and the restored `Message.article_id`.

### 2026-09-08 — modules 10 & 11: post and home_feed

Both already matched app_old exactly on paths, query params, bodies, response models and
status codes. Work was dead-code removal and one real performance regression.

**15 zero-byte stubs deleted** (8 post, 7 home_feed) after checking each: **none was imported
anywhere**. Same scaffolding pattern as onboarding and connections. X7 closed — the tree now
has **0** empty non-`__init__` .py files, down from 72.

**X11/HF-1 fixed — and HF-6 with it.** app_old ran the four source pipelines (post, news,
connection, group) inside a `ThreadPoolExecutor`; app_new called them sequentially, so a home
feed cost the *sum* of four round-trips instead of the slowest one. Restored, together with
app_old's `_in_own_session` helper: a SQLAlchemy Session is not thread-safe and `db` belongs to
the request thread, so each pipeline now opens and closes its own. A pipeline that raises still
degrades to empty rather than failing the whole feed, as app_old did.

**Two more GAP_ANALYSIS claims are wrong:**
* *PO-4 "`mark_seen` unrouted, seen-state never recorded"* — `POST /posts/recommendation/seen`
  is routed at `post/recommendation/router.py:39`, exactly as in app_old.
* *PO-5 "`_ROLE_NAMES` duplicated in 3+ files"* — it is **defined once** in
  `recommendation/constants.py` and imported by the other four.

Gate: `test_home_feed.py` PASS.

---

## Sequencing note — what is deliberately deferred

Contract parity was prioritised over repository extraction, because the live client breaks on
the former and not the latter. **That work remains open for `connections`, `post`, `groups` and
`news`**: their `data/repository.py` files were empty scaffolding (now deleted rather than left
as misleading stubs), so ~20 use-case files still run `db.query` directly. `profile`, `chat`,
`safety`, `deeplink`, `verification` and `onboarding` are done and are the pattern to follow.

This is deliberate: mechanically relocating ~90 live queries with no database to test against
is the highest-risk, lowest-user-value change in the backlog, and the gates here verify
contract shape, not query results.

## Before deploying — what these gates do NOT cover

Every test fakes the repository. Nothing here has touched a real database. Before release:
1. Run against a real DB and smoke-test from the actual client.
2. Confirm `messages.article_id` exists in production (app_old declares it, so it should).
3. Decide the `/news/feed/government` mapping (cluster 1 vs a new `is_government` column).
4. Register the news compatibility routers in `main.py` — `router`, `compat_router` **and**
   `compat_admin_router` (main.py is not in this repo).
5. Re-check `posts.taste_update`, now 15 min where app_old ran 12 h.


### 2026-09-08 — final sweep

The remaining **33** zero-byte stubs were checked individually: **every one was unimported**.
Deleted, along with the now-empty `core/ai/` and `core/storage/` packages. **X7 fully closed —
0 empty non-`__init__` .py files, from 72.** Note this includes `core/ai/gemini.py`,
`core/security/firebase.py`, `core/storage/supabase.py`, `shared/exceptions/base.py`,
`shared/utils/{time_decay,vector_math}.py` and `shared/schemas/pagination.py`: GAP_ANALYSIS
C-5/C-6/C-7 budgeted ~5 hrs to "wire" these, but nothing imports them and the real
implementations already live elsewhere (`news/application/tasks.py` for Gemini,
`core/security/jwt_handler.py` + `onboarding/data/adapters/firebase.py` for auth,
`shared/utils/storage.py` for Supabase).

## Final state

| gate | before | after |
|---|---|---|
| module packages importing | 6/11 | **11/11** |
| unresolved intra-app imports | 15 | **0** |
| app_old endpoints missing from app_new | 24 | **0** |
| zero-byte stub files | 72 | **0** |
| framework imports in any `domain/` | 0 | **0** |
| executable gates | 0 | **11 passing** |

Still open, deliberately (see sequencing note): **25 files** run `db.query` outside `data/`
and **12** import from `presentation/`, all in connections, post, groups and news.


### 2026-09-08 — response-BODY parity (the gap the endpoint diff could not see)

The endpoint diff proves *paths* match. It says nothing about the JSON. A field-by-field
comparison of every pydantic model in both trees found that **news' compat endpoints returned
the wrong body**: the URLs resolved but the client would have received unusable JSON.

app_old feeds return `{"articles": [NewsCard], "next_cursor": ...}` with keys like
`article_id`, `time_on_platform`, `summary_bullets`, `geo_category`, `is_government`,
`impact_direction`, `impact_score`, `like_count`, `is_liked`. The compat endpoints were
returning app_new's `ArticleOut` (`id`, `summary`, `url`, `cluster_id`, `severity`, `scope`, …)
— a completely different object.

Fixed:
* `NewsCard`, `NewsCardDetail`, `NewsFeedPage`, `NewsLikeOut`, `NewsSaveOut`, `NewsShareOut`
  restored field-for-field into `news/presentation/schemas.py`.
* `use_cases/card_adapter.py` maps NewsArticle -> NewsCard, including app_old's exact
  `time_on_platform` wording ("3h" / "Yesterday" / "5 days ago") which the client renders raw.
* `use_cases/compat_feeds.py` returns `NewsFeedPage` with app_old's `limit` +
  `cursor_article_id` paging for `/news/feed`, `/news/trending`, `/news/feed/saved` and the
  three geo tabs; `/news/articles/{id}` returns `NewsCardDetail`.
* like/save/share now return `{article_id, is_liked}` / `{article_id, is_saved}` /
  `{article_id, platform}` as app_old did — `platform` is echoed back on share.

**Route-order requirement:** `compat_router` and the app_new `router` both define
`GET /news/feed` with different params and bodies. FastAPI matches in registration order, so
**main.py must register `compat_router` first.** Documented in `news/__init__.py`.

**New permanent gate: `test_contracts.py`.** Walks every app_old endpoint, collects every
pydantic model reachable from it (request body, `response_model`, `.model_dump()` returns, and
anything nested or inherited), and asserts each exists in app_new with identical fields.
`Optional[X]` and `X | None` are normalised; fields app_new *adds* with a default are treated
as additive. **72 client-reachable models across 137 endpoints — all match.**

Models still absent from app_new are confirmed **not** client-reachable: `RawArticleOut`,
`EnrichedArticleOut`, `CanonicalArticle`, `LLMEnrichment`, `FactorScore`, `ImpactPayload`,
`ArticleRecommendationScoreOut`, `FeedRankingCacheOut`, `IngestResult`, `EnrichResult`
(all describe app_old's deleted GNews/Groq tables) and connections' `UserCreate`/`UserUpdate`
(from the dead `routes/users.py`).


### 2026-09-08 — live-database verification + schema parity

Everything before this faked the repository. This runs the **real SQL** against a throwaway
Postgres 14 cluster built from app_new's own models.

```
sh _migration/test_schema.sh          # builds BOTH schemas, diffs them
python3.12 _migration/test_live_db.py # real requests, real queries
```

**Schema parity — the answer to "make the tables exactly match old":**

| | |
|---|---|
| app_old tables | 55 |
| app_new tables | 47 |
| **shared tables** | **42** |
| **breaking column differences on shared tables** | **0** |

Every shared table matches on column name, type, nullability and length — including
`messages` (17 columns both sides, `article_id` present in both after the restore). The only
divergence is news: app_old's 13 tables (`news_raw_articles`, `news_enriched_articles`,
`news_likes`, `news_saves`, `news_shares`, `news_views`, `news_article_stats`,
`news_interaction_events`, `news_raw_trending`, `news_recommendation_scores`,
`news_feed_ranking_cache`, `user_news_taste`, `user_news_taste_profiles`) are replaced by
app_new's 5 (`news_articles`, `news_sources`, `news_engagement`, `news_trending`,
`user_cluster_taste`). **That is a data migration, not a code fix — see the deploy list.**

**A crash only the live run could find.** `compat_router.get_article_detail` (the endpoint)
shadowed the imported use case of the same name, so `GET /news/articles/{id}` recursed until
`RecursionError`. Every static gate passed it. Renamed, and a tree-wide scan for
"function shadows an import and calls itself" now reports none.

`test_live_db.py` executes real queries and asserts app_old's shapes:
safety (block/unblock/report, **including the Profile outerjoin that returns `name` and
`avatar_url`**, pagination keys, 409/404), deeplink (post/user/news links, business join in the
description, 404s), news compat (`NewsFeedPage` + all 16 `NewsCard` keys, `source_name` from
the join, `time_on_platform` format, like/save/share bodies, saved feed, the global/domestic/
government tabs actually filtering, `NewsCardDetail`, and batch dropping stale + unknown
events), admin counts, and verification (**asserting `profile.is_user_verified` is really
persisted**).


### 2026-09-08 — zero architectural violations

The deferred work is done. **~180 `db.query` calls across 25 files** moved into per-module
repositories behind generated ABCs, one module at a time, each verified against the live DB.

| module | queries moved | interface |
|---|---|---|
| connections | 31 | `IConnectionsRepository` (28) |
| groups | 29 + ANN | `IGroupsRepository` (35) |
| post | 52 | `IPostRepository` (41) |
| news | 47 | `INewsRepository` (32) |
| chat (socket handlers) | 4 | added to `IChatRepository` (21) |

`_migration/gen_repo_interface.py` generates each ABC from its concrete class, so the two
cannot drift — and it rewrites `Session` to `Any` in return types so the `session` escape
hatch (needed by cross-module helpers like `get_amplify_weights`) never leaks SQLAlchemy into
the domain layer.

Duplication removed along the way: connections had `_fmt_profile` and `_load_profiles_bulk`
byte-identical in **four** files and two copies of `_bulk_statuses`; post had
`_active_profile_ids`/`_is_liked`/`_is_saved`/`_get_post_or_raise` repeated across five.
Each is now one repository method or one formatter.

`news/application/tasks.py` moved to `news/data/tasks.py`: they are APScheduler
data-maintenance jobs that open and own their own Session — ingest, trending recalc, taste
aggregation, archival — not request-handling use cases, and their SQL is job-specific.

**51 pydantic models** moved from `presentation/schemas.py` to `application/schemas.py` in
news, groups and home_feed (the convention post and profile already used), with presentation
re-exporting every name so the wire format is untouched.

**Bugs the live baseline caught before they shipped** — this is why the net was built first:
* connections: the generated ABC still named two methods I had renamed → **every** connections
  endpoint 500'd.
* groups: a dangling `query.order_by(...)` left behind when the join-requests listing moved →
  that endpoint 500'd.
* post: `mark_seen.py` got the signature rewrite but not the interface import → the whole post
  package failed to import.
* news: `compat_router.get_article_detail` shadowed the imported use case of the same name →
  `GET /news/articles/{id}` recursed to `RecursionError`.
* two real transcription bugs caught while reading: `MessageRequest` uses `sent_at` not
  `created_at`, and withdraw only removes **pending/declined** requests.

New permanent gate `test_architecture.py` enforces all of it: no SQL outside `data/`, no
application→presentation import, a dependency-free domain, no zero-byte stubs, no module
shadowed by a same-named package, and all **10** repositories implementing their interface
with no unimplemented abstract methods.

## Live-DB gates — how to run them

They need a local Postgres 14+ with pgvector. A throwaway cluster:

```sh
SOCK=/tmp/vjpg; PGDATA=$SOCK/data; PORT=54329
mkdir -p "$PGDATA" && initdb -D "$PGDATA" -U vanijyaa --auth=trust
pg_ctl -D "$PGDATA" -o "-p $PORT -k $SOCK -c listen_addresses=127.0.0.1" -l "$SOCK/log" start
psql -h 127.0.0.1 -p $PORT -U vanijyaa -d postgres -c "CREATE DATABASE vanijyaa_test"
sh _migration/run_gates.sh          # skips the live gates if Postgres is absent
```

`run_gates.sh` runs everything: static imports, the architecture gate, the endpoint +
model contract gate, the schema diff, the live-DB tests, and every module test.


### 2026-09-08 — the deploy checklist, done

The five items left for the user are now four done and one they must run.

**1. News data migration — `migrations/001_news_v1_to_v2.sql`, tested end to end.**
app_old's 13 news tables -> app_new's 5, with the key discovery that **app_new's 10 clusters
are app_old's 10 `RELEVANCY_MATRIX` factors renamed, in order** — a clean 1:1 map, not a
judgement call:

| app_old factor | cluster |
|---|---|
| policy_regulation / geopolitical_macro / supply_disruptions / financial_mechanics / structural_shifts | 1 / 2 / 3 / 4 / 5 |
| long_term_demand / deal_flow / price_volatility / local_operational / indirect_general | 6 / 7 / 8 / 9 / 10 |

Article **ids are preserved**, so existing `vanijyaa://news/<uuid>` deep links keep resolving.
`profile_id` (int) resolves to `user_id` (uuid) via `profile.users_id`. Likes, saves, shares,
views and interaction events all fold into `news_engagement` with app_old's event-type mapping
and the 600 000 ms dwell cap. The migration is **idempotent** (third run inserts nothing) and
**touches nothing in app_old** — rollback is just pointing the code back.
Gate: `_migration/test_news_migration.sh` — builds both schemas in a scratch DB, loads v1
fixtures covering enriched/unenriched/duplicate articles, a missing source, an over-cap dwell
and an unmappable taste dimension, runs the migration three times and asserts 24 properties.

**2. Router registration — `app/routers.py`.** main.py now calls one function instead of
listing routers. It encodes the ordering constraint: `news.compat_router` and `news.router`
both declare `GET /news/feed` with different params and bodies, and FastAPI dispatches to the
first match, so compat must register first. Building the real app also found **three app_old
endpoints that were unreachable** — `POST /posts/interactions/batch`, `/jobs/taste-update`,
`/jobs/ignore-detect` — because `post/recommendation/session_taste/router.py` was never
registered anywhere. And two more dead scaffolding packages went: `news/feed/` and
`news/ingestion/` were routers with **zero** endpoints and comment-only service/schema files.
Gate: `test_app_routes.py` — asserts all **137** app_old endpoints resolve on the assembled
app (153 routes, 16 routers).

**3. `messages.article_id` in production — cannot verify from here.**
`migrations/000_preflight.sql` is a read-only script that answers it against your database,
along with the v1 news volume, exactly what the migration will skip, any factor the map does
not cover, and any orphaned `profile_id`s whose interactions would be dropped.
`migrations/002_add_missing_columns.sql` adds the column if it is absent (it is a no-op on a
database that ran app_old, which declares it).

**4. `/news/feed/government` — the approximation is gone.** `is_government` is a real column on
`NewsArticle` again, populated by the Gemini classifier (prompt field added) and by a keyword
rule in the fallback path. app_old's own config says the flag is *"INDEPENDENT of geo_category
and primary_factor"*, which is exactly why cluster 1 was never equivalent. The feed now filters
`is_government IS TRUE`, and the migration carries the historical values across.

**5. `posts.taste_update` 12 h -> 15 min is a FIX, not a regression.** `_BATCH_SIZE = 500` is
identical in both trees and the job drains at most 500 unprocessed events per run. At 12 h that
is **1 000 events/day**; above that the backlog grew forever and taste never caught up. At
15 min it is **48 000/day**. Interval left alone.
