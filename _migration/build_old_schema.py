"""Build app_old's schema into vanijyaa_old, so it can be diffed against app_new's.
Run in its own process — app_old and app_new both claim the package name `app`."""
import os, sys, types, importlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "pkgroot_old"))

DSN = "postgresql+psycopg2://vanijyaa@127.0.0.1:54329/vanijyaa_old"
os.environ.update(
    SYNC_DATABASE_URL=DSN, DATABASE_URL=DSN.replace("psycopg2", "asyncpg"),
    DATABASE_STORAGE_URL="https://stub.supabase.co", DATABASE_SERVICE_KEY="k",
    JWT_SECRET_KEY="t", GNEWS_API_KEY="x", GROQ_API_KEY="x",
)

_cred = types.SimpleNamespace(Certificate=lambda *a, **k: object())
_auth = types.SimpleNamespace(verify_id_token=lambda *a, **k: {})
_fb = types.ModuleType("firebase_admin")
_fb.App, _fb.credentials, _fb.auth = object, _cred, _auth
_fb.get_app = lambda *a, **k: object(); _fb.initialize_app = lambda *a, **k: object()
_sb = types.ModuleType("supabase"); _sb.create_client = lambda *a, **k: object(); _sb.Client = object
for n, m in [("firebase_admin", _fb), ("firebase_admin.credentials", _cred),
             ("firebase_admin.auth", _auth), ("supabase", _sb)]:
    sys.modules.setdefault(n, m)

MODELS = [
    "app.modules.profile.models",
    "app.modules.auth.models",
    "app.modules.post.models",
    "app.modules.post.post_recommendation_module.models",
    "app.modules.post.post_user_interaction.models",
    "app.modules.chat.data.models",
    "app.modules.groups.models",
    "app.modules.connections.models",
    "app.modules.safety.models",
    "app.modules.verification.models",
    "app.modules.news_new.ingestion.models",
    "app.modules.news_new.intelligence.models",
    "app.modules.news_new.news_user_interaction.models",
    "app.modules.news_new.news_recommendation_engine.models",
    "app.modules.taste.global_taste.data.models",
]
loaded, failed = [], []
for m in MODELS:
    try: importlib.import_module(m); loaded.append(m)
    except Exception as e: failed.append((m, f"{type(e).__name__}: {e}"))

from sqlalchemy import create_engine, text
from app.core.database.base import Base
eng = create_engine(DSN, future=True)
with eng.begin() as c:
    c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
Base.metadata.create_all(eng)
print(f"app_old: {len(loaded)} model modules, {len(Base.metadata.tables)} tables")
for m, e in failed: print("  FAILED", m, e[:110])
