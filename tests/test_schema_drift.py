"""The ORM and the migration chain must describe the same schema.

Columns kept being added straight to production by hand — profile.avatar_url,
group_deals.deal_type, personal_deals.deal_type — so a database built from the
migrations did not match the models and could not even insert a profile. Worse,
news_raw_trending.unique_profiles was in the ORM and in NEITHER, so the trending
job was one popular article away from failing in production.

Run against a database freshly migrated from empty; anything it reports is drift
that will bite the next time somebody builds an environment or restores a backup.
"""
import os
import sys

DB = os.environ.get("SYNC_DATABASE_URL", "")
if "localhost" not in DB and "127.0.0.1" not in DB:
    sys.exit("refusing to run: SYNC_DATABASE_URL is not a local database")

import main  # noqa: F401,E402  — imports every model onto the metadata
from sqlalchemy import inspect  # noqa: E402

from app.core.database.base import Base          # noqa: E402
from app.core.database.session import engine     # noqa: E402

insp = inspect(engine)
db_tables = set(insp.get_table_names())
orm_tables = set(Base.metadata.tables)

problems = [f"table {t} is in the ORM but no migration creates it"
            for t in sorted(orm_tables - db_tables)]

for name in sorted(orm_tables & db_tables):
    db_cols = {c["name"] for c in insp.get_columns(name)}
    orm_cols = {c.name for c in Base.metadata.tables[name].columns}
    problems += [f"{name}.{c} is in the ORM but no migration creates it"
                 for c in sorted(orm_cols - db_cols)]

if problems:
    print(f"FAIL ({len(problems)})")
    for p in problems:
        print("   ", p)
    sys.exit(1)
print(f"PASS - schema drift: {len(orm_tables)} ORM tables all built by migrations")
