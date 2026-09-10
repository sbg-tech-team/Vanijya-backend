"""Create the schema and seed fixtures in the dedicated smoke database."""
import os
os.environ.setdefault("SMOKE_DB", "vanijyaa_smoke")
DSN = f"postgresql+psycopg2://vanijyaa@127.0.0.1:{os.environ.get('VJ_PGPORT','54329')}/{os.environ['SMOKE_DB']}"
os.environ["SYNC_DATABASE_URL"] = DSN
os.environ["DATABASE_URL"] = DSN.replace("psycopg2", "asyncpg")

import _db  # noqa: E402
import _seed  # noqa: E402

_db.import_all_models()
_db.create_schema()
ids = _seed.seed(_db.SessionTesting())
open("/tmp/seed_ids.txt", "w").write("|".join(str(x) for x in [
    ids["me"]["profile_id"], ids["article_id"], ids["post_id"],
    ids["group_id"], ids["other"]["user_id"]]))
print(f"smoke DB seeded: profile {ids['me']['profile_id']}, article {ids['article_id']}")
