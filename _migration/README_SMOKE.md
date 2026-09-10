# Smoke testing against a real server

Unlike every other gate, this speaks HTTP to a real uvicorn process backed by a
real Postgres, with **no stubs anywhere**. It exercises write paths, and each
module runs in its own parallel worker so a failure is attributed to one module.

## 1. Postgres with SSL

`core/database/session.py` hardcodes `connect_args={"sslmode": "require"}`, so a
plain local cluster will be refused. For a throwaway one:

```sh
SOCK=/tmp/vjpg; PGDATA=$SOCK/data; PORT=54329
mkdir -p "$PGDATA" && initdb -D "$PGDATA" -U vanijyaa --auth=trust
openssl req -new -x509 -days 365 -nodes -text -out "$PGDATA/server.crt" \
  -keyout "$PGDATA/server.key" -subj "/CN=localhost"
chmod 600 "$PGDATA/server.key"
pg_ctl -D "$PGDATA" -l "$SOCK/log" -o "-p $PORT -k $SOCK -c listen_addresses=127.0.0.1 \
  -c ssl=on -c ssl_cert_file=$PGDATA/server.crt -c ssl_key_file=$PGDATA/server.key" start
psql -h 127.0.0.1 -p $PORT -U vanijyaa -d postgres -c "CREATE DATABASE vanijyaa_test"
```

## 2. A venv with the REAL dependencies

The other gates stub socketio / supabase / apscheduler / google-genai. Smoke must not:

```sh
python3.12 -m venv /tmp/vjvenv
/tmp/vjvenv/bin/pip install fastapi uvicorn sqlalchemy psycopg2-binary pydantic \
  pydantic-settings python-socketio supabase apscheduler google-genai feedparser \
  pyjwt httpx redis firebase-admin python-multipart email-validator pgvector numpy
```

> Note: `numpy` and `feedparser` are imported by app code but appear in no
> requirements file in this repo. Make sure your deploy image has them.

## 3. Redis

The app falls back to `redis://localhost:6379/0`, which on a dev machine is very
likely **your own Redis**. Use an isolated one so the smoke run cannot touch it:

```sh
redis-server --port 6399 --daemonize yes --dir /tmp/vjredis --save '' --appendonly no
```

`serve.py` defaults to `redis://127.0.0.1:6399/0`; override with `SMOKE_REDIS_URL`.
`test_taste_live.py` uses db **15** on the same instance.

## 4. Seed, serve, smoke

```sh
cd _migration && python3.12 -c "
import _db, _seed; _db.import_all_models(); _db.create_schema()
ids=_seed.seed(_db.SessionTesting())
open('/tmp/seed_ids.txt','w').write('|'.join(str(x) for x in
  [ids['me']['profile_id'], ids['article_id'], ids['post_id'], ids['group_id'], ids['other']['user_id']]))"
cd .. && /tmp/vjvenv/bin/uvicorn --app-dir _migration serve:app --port 8099 &
/tmp/vjvenv/bin/python _migration/build_smoke_ctx.py       # mints a real JWT via /auth/dev-token
/tmp/vjvenv/bin/python _migration/smoke.py                 # all modules, in parallel
/tmp/vjvenv/bin/python _migration/smoke.py --module news   # or just one
```

Run it **twice**. The second pass exercises duplicate/revisit code paths that a
fresh database never reaches — that is how the `record_revisit_event` crash was
found.

## 5. Against production data

Point `_db.py`'s DSN at a **restored copy** of production, skip `create_schema()`,
run `migrations/000_preflight.sql` first, and use a real login instead of
`/auth/dev-token` (it is `DEBUG`-gated and must stay off in production).
