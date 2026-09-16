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
| `RENDER_DEPLOY_HOOK_URL` | Render → the service → Settings → **Deploy Hook** |
| `SYNC_DATABASE_URL` | The production `postgresql+psycopg2://…` URL. Alembic uses this one. |

Until both are set the pipeline still runs the tests, but skips migrating and
deploying with a warning instead of failing. Merging stays safe.

### 2. Render env vars

Set every `sync: false` key from `render.yaml` in the dashboard. Two are new and
the calling endpoints fail at runtime without them:

    STREAM_API_KEY
    STREAM_API_SECRET

### 3. Turn Render's own auto-deploy OFF

`render.yaml` sets `autoDeploy: false`, but that only applies if the service is
Blueprint-managed. **If the service was created by hand in the dashboard, Render
ignores `render.yaml` entirely** — switch Auto-Deploy off in the service
settings yourself.

This matters: if Render deploys on push *and* the pipeline deploys after
migrating, Render wins the race and ships code before its migration has run.
The pipeline must be the only trigger.

## What the pipeline does

**verify** — architecture gate, calling tests, post-indexing test, and a full
app import that registers every router. Runs on dummy DB credentials; these
checks never open a connection. A failure here stops the deploy.

**deploy** — `alembic upgrade head` against production, *then* the Render hook.
That order is the point: migrations have never run automatically on this
service, so every schema change used to depend on someone remembering.

## Deploying by hand

Actions tab → **deploy** → *Run workflow*. Same path, same gates.

## Rolling back

Revert the commit and push to `main`. Migrations do not auto-revert — if the bad
deploy included one, downgrade it yourself:

    alembic downgrade -1

## Known gap

`app/core/scheduler.py` pings `https://vanijyaa-backend.onrender.com/` to keep
the instance warm. That host currently returns `x-render-routing: no-server`, so
the ping fails every 10 minutes. Point it at the real URL, or make it an env var.
