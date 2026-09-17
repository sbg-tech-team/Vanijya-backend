"""Real Postgres harness: builds app_new's schema and hands out real Sessions.

Everything else in _migration/ fakes the repository. This does not — it executes
the actual SQL, which is the only way to catch a wrong column name, a bad join
or a broken relationship.
"""
import os

PGPORT = os.environ.get("VJ_PGPORT", "54329")
# the smoke suite uses its own DB (VJ_DB) so the other gates can freely
# DROP SCHEMA on vanijyaa_test without wiping a running server's data.
DB = os.environ.get("VJ_DB", "vanijyaa_test")
DSN = f"postgresql+psycopg2://vanijyaa@127.0.0.1:{PGPORT}/{DB}"
os.environ["SYNC_DATABASE_URL"] = DSN
os.environ["DATABASE_URL"] = DSN.replace("psycopg2", "asyncpg")

import _boot  # noqa: E402,F401  (path + SDK stubs; must come after the env vars)

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

engine = create_engine(DSN, future=True)
SessionTesting = sessionmaker(bind=engine, autoflush=False, future=True)


def import_all_models():
    """Import every module's models so Base.metadata is complete."""
    import importlib
    mods = [
        "app.modules.profile.data.models",
        "app.modules.onboarding.data.models",
        "app.modules.post.data.models",
        "app.modules.chat.data.models",
        "app.modules.groups.data.models",
        "app.modules.connections.data.models",
        "app.modules.news.data.models",
        "app.modules.safety.data.models",
        "app.modules.verification.data.models",
        "app.recommendation.global_taste.models",
        "app.modules.post.data.recommendation_models",
    ]
    loaded, failed = [], []
    for m in mods:
        try:
            importlib.import_module(m); loaded.append(m)
        except Exception as e:
            failed.append((m, f"{type(e).__name__}: {e}"))
    return loaded, failed


def create_schema():
    from app.core.database.base import Base
    with engine.begin() as c:
        c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
        c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    return sorted(Base.metadata.tables)
