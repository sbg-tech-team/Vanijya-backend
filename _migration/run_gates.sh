#!/bin/sh
# All migration gates. Run from the repo root: sh _migration/run_gates.sh
set -e
cd "$(dirname "$0")/.."
echo "== static import resolution =="
python3 _migration/check_imports.py app_new || true
echo "== endpoint contract diff (app_old is the source of truth) =="
python3 _migration/extract_contracts.py app_old _migration/old.json >/dev/null
python3 _migration/extract_contracts.py app_new _migration/new.json >/dev/null
python3 _migration/diff_contracts.py | sed -n '/IN OLD, NOT IN NEW/,$p'
echo "== architecture gate =="
python3.12 _migration/test_architecture.py | tail -2
echo "== whole-tree contract gate =="
python3.12 _migration/test_contracts.py | tail -2
echo "== live-DB gates (skipped if no local Postgres on :54329) =="
if pg_isready -h 127.0.0.1 -p "${VJ_PGPORT:-54329}" >/dev/null 2>&1; then
  sh _migration/test_schema.sh | tail -2
  python3.12 _migration/test_live_db.py | tail -1
  sh _migration/test_news_migration.sh | tail -1
else
  echo "  SKIPPED - no Postgres on :${VJ_PGPORT:-54329} (see LEDGER.md)"
fi
echo "== live Redis taste gate (skipped if no Redis on :6399) =="
if redis-cli -p "${VJ_REDIS_PORT:-6399}" ping >/dev/null 2>&1; then
  (cd _migration && SMOKE_REDIS_URL="redis://127.0.0.1:${VJ_REDIS_PORT:-6399}/15" \
     python3.12 test_taste_live.py | tail -1)
else
  echo "  SKIPPED - no Redis on :${VJ_REDIS_PORT:-6399} (redis-server --port 6399 --daemonize yes)"
fi
echo "== module tests =="
cd _migration
python3.12 test_imports.py | tail -1
for t in test_*.py; do
  [ "$t" = "test_imports.py" ] && continue
  printf "  %-22s " "$t"; python3.12 "$t" 2>/dev/null | tail -1
done
