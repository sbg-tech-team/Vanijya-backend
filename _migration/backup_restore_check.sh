#!/usr/bin/env bash
# Take a production backup and prove it restores.
#
#   _migration/backup_restore_check.sh
#
# A backup nobody has restored is not a backup. This dumps production, restores
# into a throwaway local database, and compares row counts table by table. It
# reads only from production and writes only locally.
#
# Needs pg_dump/pg_restore matching the SERVER version (17):
#   brew install postgresql@17
set -euo pipefail

PGBIN="${PGBIN:-/opt/homebrew/opt/postgresql@17/bin}"
DUMP="${DUMP:-/tmp/prod_backup.dump}"
RESTORE_DB="${RESTORE_DB:-vanijyaa_restore}"
: "${SYNC_DATABASE_URL:?set SYNC_DATABASE_URL to the production database}"

PLAIN="${SYNC_DATABASE_URL/postgresql+psycopg2:\/\//postgresql://}"

echo "==> dumping production"
"$PGBIN/pg_dump" --no-owner --no-acl --no-comments -Fc "$PLAIN" -f "$DUMP"
ls -lh "$DUMP" | awk '{print "    size:", $5}'

echo "==> restoring into $RESTORE_DB"
psql -d postgres -qc "DROP DATABASE IF EXISTS $RESTORE_DB"
psql -d postgres -qc "CREATE DATABASE $RESTORE_DB"
psql -d "$RESTORE_DB" -qc "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;"
# Supabase ships vault/transaction_timeout that a plain server does not have.
# Those errors are expected and touch no application data; row counts below are
# the thing that decides whether the restore is good.
"$PGBIN/pg_restore" --no-owner --no-acl -d "postgresql://$(whoami)@localhost:5432/$RESTORE_DB" "$DUMP" \
  2>&1 | grep -v "supabase_vault\|vault.secrets\|transaction_timeout\|NULLS" || true

echo "==> comparing row counts"
RESTORE_URL="postgresql+psycopg2://$(whoami)@localhost:5432/$RESTORE_DB" \
python3 - <<'PY'
import os, sys
from sqlalchemy import create_engine, text
prod = create_engine(os.environ["SYNC_DATABASE_URL"])
rest = create_engine(os.environ["RESTORE_URL"])
with prod.connect() as c:
    tables = [r[0] for r in c.execute(text(
        "select table_name from information_schema.tables "
        "where table_schema='public' order by table_name"))]
bad = []
for t in tables:
    def n(e):
        try:
            with e.connect() as c:
                return c.execute(text(f'select count(*) from "{t}"')).scalar()
        except Exception:
            return None
    a, b = n(prod), n(rest)
    if a != b:
        bad.append(f"  {t}: production {a}, restored {b}")
print(f"    {len(tables)} tables compared")
if bad:
    print("FAIL - restore does not match production:")
    print("\n".join(bad))
    sys.exit(1)
print("PASS - every table restored with matching row counts")
PY
