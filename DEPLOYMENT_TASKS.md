# Pre-Deployment Tasks

Status as of this cutover session. `app/` is now the Clean Architecture rewrite;
`app_v1_backup/` is the previous live code, kept as the rollback path (do not delete).

**Read [`_migration/LEDGER.md`](_migration/LEDGER.md) first** for the full module-by-module
audit history. Run `sh _migration/run_gates.sh` to confirm the gates still pass on your machine
(needs `_migration/pkgroot/app` to be a real directory junction to `../app` — see note below).

---

## Done in this cutover

- **Router registration** — `main.py` now calls `app.routers.register_routers(app)` instead of
  listing routers by hand.
- **News module** — reverted from an earlier RSS+Gemini rewrite back to matching
  `app_v1_backup`'s actual live behavior byte-for-byte: same GNews+Groq pipeline, same DB tables
  (`news_raw_articles`, `news_enriched_articles`, etc. — already live, unchanged), same 17 URLs,
  same `ok()` envelope, same batch/session-taste rules. **No news data migration is needed** —
  the schema was never changed.
- **`requirements.txt`** — added `requests` (the news module's GNews/Groq adapters call it
  directly). `feedparser` was added and then removed again once news reverted away from RSS.
  `numpy` and `sentry-sdk[fastapi]` were already present.
- **Alembic** — `alembic/env.py`'s model-import block rewritten to the new module paths; the
  2 migrations that were pending at the start of this session (`add_user_global_taste`,
  `add_location_fields_to_enriched`) are applied — DB is at head.
- **`tests/test_security_fixes.py`** — rewritten for the new module paths (mock targets moved
  from flat `app.modules.X.router` to `app.modules.X.presentation.router` / `application.service`
  as appropriate); `GET /posts/` dropped from the suite since it's commented out in both trees.
  53/53 passing against the real app via `TestClient`.
- **Sentry — deliberately deferred**, not part of this cutover. `app/core/` has no
  `monitoring.py`; the app runs without Sentry error tracking until this is revisited separately.

---

## Still open

### External services never exercised
No credentials existed in the environment these gates ran in, so **none of these has ever been
called for real**:

| Service | Where | Smoke test |
|---|---|---|
| Firebase | `onboarding/data/adapters/firebase.py` | `POST /auth/firebase-verify` with a real ID token |
| Supabase storage | `shared/utils/storage.py` | `GET /profile/avatar-upload-url?content_type=image/jpeg`, then upload |
| GNews + Groq | `news/data/adapters/{gnews,groq}.py` | run the ingest pipeline once (`POST /news/admin/ingest`), confirm articles land in `news_raw_articles` and get enriched |
| Surepass | `verification/data/adapters/surepass.py` | `POST /verification/kyc/pan` in sandbox |
| MSG91 | `onboarding/application/service_msg91.py` | per your OTP flow |

Firebase init is lazy — a bad `service.json` no longer breaks startup, it fails on first use.
Check the logs, not just the boot.

### Socket.IO real-time
Never exercised end-to-end in this session — no client was connected.
`app/modules/chat/presentation/connection_manager.py` holds the single `sio` server (single-worker
only, per its own docstring — `uvicorn main:app` with no `--workers` flag, matching `render.yaml`).
Verify: two clients connect, a DM/group message delivers via `new_message`/`new_group_message`,
and `POST /news/interactions/send/{id}` delivers a shared article into chat.

### Load and latency
Never measured under real traffic. Watch especially `posts.taste_update` (runs every 15 min,
`_BATCH_SIZE=500` → up to 48,000 events/day).

### `home_feed` module removed
`app/modules/home_feed/` (`GET /feed/home`, `POST /feed/engagement`) was removed entirely — it
never had a real implementation behind it (`POST /feed/engagement` was a documented no-op, and
the type-mix weighting it exposed was hardcoded, not dynamic). All references to it — router
registration in `app/routers.py`, the `_migration` gates, `tests/test_security_fixes.py` — were
cleaned up alongside its removal.

### `sslmode=require` is hardcoded
`app/core/database/session.py` hardcodes `connect_args={"sslmode": "require"}`. Fine for managed
Postgres; blocks any environment without SSL. Consider making it config-driven if a local/dev
instance needs to connect without it.

---

## Local gate suite

```sh
sh _migration/run_gates.sh          # static gates; live-DB/Redis ones skip if absent locally
pytest tests/test_security_fixes.py -v
```

`_migration/pkgroot/app` must be a real directory junction to the repo's `../app` (not a plain
copy — a copy silently goes stale the moment you edit `app/` again and the gates will report
false failures/passes against old code). On Windows:
```powershell
New-Item -ItemType Junction -Path "_migration\pkgroot\app" -Target "app"
```
It's excluded from git via `_migration/.gitignore` — never commit it (git would otherwise walk
into the junction and duplicate the entire `app/` tree).

---

## Quick reference

| | |
|---|---|
| Chronological decision log | [`_migration/LEDGER.md`](_migration/LEDGER.md) |
| Smoke setup | [`_migration/README_SMOKE.md`](_migration/README_SMOKE.md) |
| All gates | `sh _migration/run_gates.sh` |
| Rollback | `app_v1_backup/` is the pre-cutover code, untouched |
