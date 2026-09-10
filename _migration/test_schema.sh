#!/bin/sh
# Schema parity gate. Needs a local Postgres; see LEDGER.md "Live-DB gates".
#   sh _migration/test_schema.sh
set -e
cd "$(dirname "$0")"
PGPORT=${VJ_PGPORT:-54329}
psql -h 127.0.0.1 -p "$PGPORT" -U vanijyaa -d postgres -qc "DROP DATABASE IF EXISTS vanijyaa_old" \
     -c "CREATE DATABASE vanijyaa_old" >/dev/null
python3.12 build_old_schema.py | head -2
python3.12 -c "import _db; _db.import_all_models(); print('app_new: %d tables' % len(_db.create_schema()))"
python3.12 diff_schema.py
