#!/bin/sh
# Gate for migrations/001_news_v1_to_v2.sql.
# Builds app_old's schema + app_new's news tables in a scratch DB, loads v1
# fixtures, runs the migration three times, and asserts the result.
#   sh _migration/test_news_migration.sh
set -e
cd "$(dirname "$0")/.."
PORT=${VJ_PGPORT:-54329}
PSQL="psql -h 127.0.0.1 -p $PORT -U vanijyaa -d vanijyaa_mig -q -v ON_ERROR_STOP=1"

psql -h 127.0.0.1 -p "$PORT" -U vanijyaa -d postgres -qc "DROP DATABASE IF EXISTS vanijyaa_mig" \
     -c "CREATE DATABASE vanijyaa_mig" >/dev/null
python3.12 _migration/build_mig_schema.py
$PSQL -f _migration/fixtures_news_v1.sql
for i in 1 2 3; do
  psql -h 127.0.0.1 -p "$PORT" -U vanijyaa -d vanijyaa_mig -q -v ON_ERROR_STOP=1 \
       -f migrations/001_news_v1_to_v2.sql > "/tmp/mig_run_$i.log" 2>&1
done
python3.12 _migration/assert_news_migration.py
