"""Build app_old's full schema + app_new's 5 news tables in vanijyaa_mig.
That is the real deploy shape: both live side by side while the data moves."""
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DSN = "postgresql+psycopg2://vanijyaa@127.0.0.1:%s/vanijyaa_mig" % os.environ.get("VJ_PGPORT", "54329")

# app_old and app_new both claim the package name `app`, so build each in its own process.
old = f'''
import os, sys, types, importlib
sys.path.insert(0, r"{HERE}/pkgroot_old")
os.environ.update(SYNC_DATABASE_URL=r"{DSN}", DATABASE_URL=r"{DSN}".replace("psycopg2","asyncpg"),
  DATABASE_STORAGE_URL="https://s", DATABASE_SERVICE_KEY="k", JWT_SECRET_KEY="t",
  GNEWS_API_KEY="x", GROQ_API_KEY="x")
_c=types.SimpleNamespace(Certificate=lambda *a,**k:object()); _a=types.SimpleNamespace(verify_id_token=lambda *a,**k:{{}})
_f=types.ModuleType("firebase_admin"); _f.App=object; _f.credentials=_c; _f.auth=_a
_f.get_app=lambda *a,**k:object(); _f.initialize_app=lambda *a,**k:object()
_s=types.ModuleType("supabase"); _s.create_client=lambda *a,**k:object(); _s.Client=object
for n,m in [("firebase_admin",_f),("firebase_admin.credentials",_c),("firebase_admin.auth",_a),("supabase",_s)]:
    sys.modules.setdefault(n,m)
for m in ["app.modules.profile.models","app.modules.auth.models","app.modules.post.models",
          "app.modules.chat.data.models","app.modules.groups.models","app.modules.connections.models",
          "app.modules.news_new.ingestion.models","app.modules.news_new.intelligence.models",
          "app.modules.news_new.news_user_interaction.models",
          "app.modules.news_new.news_recommendation_engine.models"]:
    importlib.import_module(m)
from sqlalchemy import create_engine, text
from app.core.database.base import Base
e=create_engine(r"{DSN}", future=True)
with e.begin() as c:
    c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    c.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
Base.metadata.create_all(e)
print("  app_old:", len(Base.metadata.tables), "tables")
'''
new = f'''
import os, sys, importlib
sys.path.insert(0, r"{HERE}")
os.environ["SYNC_DATABASE_URL"]=r"{DSN}"; os.environ["DATABASE_URL"]=r"{DSN}".replace("psycopg2","asyncpg")
import _boot
from sqlalchemy import create_engine
for m in ["app.modules.profile.data.models","app.modules.news.data.models"]:
    importlib.import_module(m)
from app.core.database.base import Base
e=create_engine(r"{DSN}", future=True)
only=[Base.metadata.tables[t] for t in
      ["news_sources","news_articles","news_engagement","news_trending","user_cluster_taste"]]
Base.metadata.create_all(e, tables=only, checkfirst=True)
print("  app_new: 5 news tables added alongside")
'''
for src in (old, new):
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip()[-400:])
    if r.returncode: sys.exit(1)
