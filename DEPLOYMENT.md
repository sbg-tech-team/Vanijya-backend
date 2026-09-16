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

**deploy** — `alembic upgrade head` against production, *then* the Render API
deploy, polled to completion so a failed build fails the job.
That order is the point: migrations have never run automatically on this
service, so every schema change used to depend on someone remembering.

## Deploying by hand

Actions tab → **deploy** → *Run workflow*. Same path, same gates.

## Rolling back

Revert the commit and push to `main`. Migrations do not auto-revert — if the bad
deploy included one, downgrade it yourself:

    alembic downgrade -1

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
