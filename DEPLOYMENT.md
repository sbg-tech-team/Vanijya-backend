# Deployment

Push to `main` → GitHub Actions verifies, migrates, then tells Render to deploy.
No manual steps once the two secrets below are set.

    .github/workflows/deploy.yml   the pipeline
    render.yaml                    the service definition

## One-time setup

### 1. Two GitHub secrets

*Settings → Secrets and variables → Actions → New repository secret*

| Secret | Where to get it |
|---|---|
| `RENDER_API_KEY` | Render → Account Settings → API Keys |
| `RENDER_SERVICE_ID` | `srv-d8v2744vikkc73f5esqg` |
| `SYNC_DATABASE_URL` | Production `postgresql+psycopg2://…`. Alembic reads this one. |

All three are already set on this repo.

Until both are set the pipeline still runs the tests, but skips migrating and
deploying with a warning instead of failing. Merging stays safe.

### 2. Render env vars

Set every `sync: false` key from `render.yaml` in the dashboard.

**Boot-critical — the app does not start without these:**

| Var | Failure if missing |
|---|---|
| `DATABASE_URL` | Settings has no default; import fails |
| `SYNC_DATABASE_URL` | Same. Alembic also reads this one |
| `DATABASE_STORAGE_URL` | `storage.py` reads it with `os.environ[...]` at import — `KeyError` |
| `DATABASE_SERVICE_KEY` | Same |

**Auth — app boots, but every login fails:**

| Var | Failure if missing |
|---|---|
| `JWT_SECRET_KEY` | `jwt_handler._secret()` raises on every token operation |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Firebase OTP verification fails, so nobody can sign in. Also FCM push |

**Per-feature — app boots, that feature fails:**

| Var | Affects |
|---|---|
| `STREAM_API_KEY`, `STREAM_API_SECRET` | Calling (**new** — not set anywhere yet) |
| `GNEWS_API_KEY`, `GROQ_API_KEY` | News ingestion and enrichment |
| `SUREPASS_TOKEN`, `SUREPASS_BASE_URL` | KYC document verification |
| `REDIS_URL` | Defaults to `localhost` — session taste, call presence and rate limiting all degrade silently |
| `SENTRY_DSN` | No error reporting |

Buckets (`POST_STORAGE_BUCKET`, `CHAT_STORAGE_BUCKET`, `GROUP_IMAGE_BUCKET`,
`GROUP_MEDIA_BUCKET`) and `JWT_ALGORITHM` all have working defaults.

### 3. Render auto-deploy stays OFF

Already `autoDeploy: no` on the service — nothing to change.

<details><summary>Why it matters</summary>

The service was created by hand, so Render **ignores `render.yaml`** — that file
is documentation of intent, not config. All real settings live in the dashboard.

If Render deployed on push *and* the pipeline deployed after migrating, Render
would win the race and ship code before its migration ran. The pipeline must be
the only trigger.
</details>

## What the pipeline does

**verify** — architecture gate, calling tests, post-indexing test, and a full
app import that registers every router. Runs on dummy DB credentials; these
checks never open a connection. A failure here stops the deploy.

**deploy** — `alembic upgrade head` against production, then
`_migration/render_deploy.py`, which:

1. records the deploy currently serving traffic,
2. triggers the new deploy and waits for it,
3. smoke-tests the live service, and
4. **rolls back to the recorded deploy if the smoke test fails.**

Render calling a deploy "live" only means the process booted and answered the
health check once — it does not mean the app works. The smoke test checks that
`/` responds, that `/openapi.json` has the full route table, and that an
unauthenticated write is refused with 401 (which catches a deploy that came up
with auth misconfigured).
That order is the point: migrations have never run automatically on this
service, so every schema change used to depend on someone remembering.

## Deploying by hand

Actions tab → **deploy** → *Run workflow*. Same path, same gates.

## Failure handling

| Failure | What happens |
|---|---|
| A test fails | Nothing deploys. Users stay on the current version. |
| Migration fails | Deploy never starts. Users stay on the current version. |
| Build fails | Render keeps serving the old version. Job fails. |
| App boots but is broken | Smoke test catches it → **automatic rollback**. |
| Health check fails at runtime | Render stops routing to the bad instance. |

### The one case that is not automatic

Migrations run **before** the deploy, so a rollback returns the *code* but not
the *schema*. Old code then runs against a newer schema.

Keep migrations backward-compatible and this is a non-event:

- Adding a column, table or index — always safe.
- Renaming or dropping — do it in two releases. Release 1 adds the new thing and
  writes to both. Release 2, once the old code is gone, drops the old thing.

If you must revert a schema change by hand:

    alembic downgrade -1

### Known limits

The service is on Render's **free plan**: one instance, no zero-downtime deploy,
and it spins down when idle. There is a short gap on every deploy, and the first
request after an idle period is slow. `scheduler.py`'s keep-alive ping covers the
idle part; removing the deploy gap needs a paid plan with more than one instance.

## Known gaps

`app/modules/onboarding/application/service_msg91.py` reads
`settings.MSG91_AUTH_KEY`, which does not exist on `Settings` (the model is
`extra = "ignore"`, so it is not picked up from the environment either). That
call would raise `AttributeError`. The module is not imported anywhere — OTP
goes through Firebase — so it is dead code. Delete it or wire the setting up;
do not leave it as a trap.

`app/core/scheduler.py` pings `https://vanijyaa-backend.onrender.com/` to keep
the instance warm. That host currently returns `x-render-routing: no-server`, so
the ping fails every 10 minutes. Point it at the real URL, or make it an env var.

## Load testing

`_migration/locustfile.py`. Run it against a LOCAL server — the production
service is a single free-plan instance, so real load there degrades the app for
actual users.

    # terminal 1: app on a throwaway database
    DB_SSLMODE=disable SYNC_DATABASE_URL=postgresql+psycopg2://…/vanijyaa_test \
      uvicorn main:app --port 8000 --workers 1

    # terminal 2
    LOAD_TOKEN=<jwt> LOAD_POST_IDS=1,2,3 locust -f _migration/locustfile.py \
      --host http://127.0.0.1:8000 --headless -u 300 -r 30 -t 30s

### Measured, one worker, database on the same machine

| Concurrent users | req/s | p50 | p95 | failures |
|---|---|---|---|---|
| 100 | 78 | 13 ms | 36 ms | 0 |
| 300 | 201 | 30 ms | 150 ms | 0 |
| 600 | 160 | 130 ms | 340 ms | 0 |

The knee is around 300 concurrent users / ~200 req/s. Past that, throughput
*falls* while latency climbs — the classic sign of saturation, not a cliff.
Nothing errored at any level.

### Why production will not reach these numbers

Those figures come from a database on localhost, about 1 ms away. Production
runs the app in Oregon and the database in `ap-northeast-1` (Tokyo). The same
endpoint measured against production:

    GET /posts/mine   1.13 – 1.86 s, median ~1.17 s

This is a synchronous, thread-per-request application, so a thread is held for
the entire database round trip. At ~15 ms per request a worker can serve many;
at ~1.2 s it can serve very few. **Co-locating the app and the database is worth
more than any amount of tuning**, and it is a config change, not a code change.

### The ceiling was the connection pool

`create_engine` was called without pool settings, so it ran on SQLAlchemy's
default: **5 connections plus 10 overflow — 15 per worker, total**. A 5000-user
run died on `QueuePool limit of size 5 overflow 10 reached` long before CPU or
memory mattered.

It bites hardest in production, where the database is a round trip away. A
request holds its connection for the whole trip, so the ceiling is roughly
`pool / latency`. At ~1.2 s to Tokyo that is **about 12 requests per second**,
however large the instance.

Now 20 + 20, with `pool_timeout=10` (fail fast rather than parking a request for
30 s) and `pool_recycle=1800`. All four are env vars — `DB_POOL_SIZE`,
`DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, `DB_POOL_RECYCLE` — and the pool size is
logged at boot next to the host.

If you raise workers, remember the pool is **per worker**: 4 workers x 40 is 160
connections, which must stay under what Supabase allows.

### Redis outage

Verified: with `REDIS_URL` pointed at a dead port, every endpoint still returned
200 and the recommendation feed degraded instead of failing.
