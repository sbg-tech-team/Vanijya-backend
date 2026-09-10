"""Diff the two live Postgres schemas built from app_old's and app_new's models.

app_old runs against the production database, so any column app_new dropped,
renamed or retyped on a SHARED table is a runtime break against real data.
"""
import sys
import psycopg2

Q = """
SELECT table_name, column_name, data_type, is_nullable,
       coalesce(character_maximum_length, -1), coalesce(numeric_precision, -1)
FROM information_schema.columns
WHERE table_schema = 'public'
ORDER BY table_name, column_name
"""

def load(db):
    with psycopg2.connect(host="127.0.0.1", port=54329, user="vanijyaa", dbname=db) as c:
        with c.cursor() as cur:
            cur.execute(Q)
            out = {}
            for t, col, typ, nullable, ln, prec in cur.fetchall():
                out.setdefault(t, {})[col] = (typ, nullable, ln, prec)
            return out

OLD, NEW = load("vanijyaa_old"), load("vanijyaa_test")

only_old = sorted(set(OLD) - set(NEW))
only_new = sorted(set(NEW) - set(OLD))
shared = sorted(set(OLD) & set(NEW))

print("=" * 78)
print(f"TABLES  old={len(OLD)}  new={len(NEW)}  shared={len(shared)}")
print("=" * 78)
print(f"\nONLY IN app_old ({len(only_old)}):")
for t in only_old: print(f"   {t:<34} ({len(OLD[t])} cols)")
print(f"\nONLY IN app_new ({len(only_new)}):")
for t in only_new: print(f"   {t:<34} ({len(NEW[t])} cols)")

print("\n" + "=" * 78)
print("COLUMN DIFFS ON SHARED TABLES  (these hit the production database)")
print("=" * 78)
breaks = 0
for t in shared:
    o, n = OLD[t], NEW[t]
    dropped = sorted(set(o) - set(n))
    added = sorted(set(n) - set(o))
    changed = sorted(c for c in set(o) & set(n) if o[c] != n[c])
    if not (dropped or added or changed): continue
    print(f"\n  {t}")
    for c in dropped:
        print(f"     DROPPED  {c:<26} was {o[c][0]}{'' if o[c][1]=='YES' else ' NOT NULL'}")
        breaks += 1
    for c in changed:
        print(f"     CHANGED  {c:<26} old={o[c]}  new={n[c]}")
        breaks += 1
    for c in added:
        req = n[c][1] == "NO"
        print(f"     ADDED    {c:<26} {n[c][0]}{'  <-- NOT NULL, needs a migration' if req else ''}")
        if req: breaks += 1
print(f"\n--- {breaks} breaking column differences on shared tables ---")
sys.exit(1 if breaks else 0)
