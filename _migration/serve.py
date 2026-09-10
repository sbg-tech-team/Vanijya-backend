import os, sys, json
HERE = "/Volumes/DEV_DATA/vanijyaa_backend_v2/comparison_architecture"
sys.path.insert(0, f"{HERE}/_migration/pkgroot")
DSN = os.environ.get("SMOKE_DSN",
    "postgresql+psycopg2://vanijyaa@127.0.0.1:54329/vanijyaa_smoke")  # NOT vanijyaa_test:
    # the other gates DROP that schema, which would wipe the seed under a running server
os.environ.update(
    SYNC_DATABASE_URL=DSN, DATABASE_URL=DSN.replace("psycopg2", "asyncpg"),
    DATABASE_STORAGE_URL="https://stub.supabase.co", DATABASE_SERVICE_KEY="k",
    JWT_SECRET_KEY="boot-test-secret", GEMINI_API_KEY="x", SUREPASS_TOKEN="x", DEBUG="true",
    # isolated Redis, so smoke never writes into a developer's own instance
    REDIS_URL=os.environ.get("SMOKE_REDIS_URL", "redis://127.0.0.1:6399/0"),
    GOOGLE_SERVICE_ACCOUNT_JSON=json.dumps({"type":"service_account","project_id":"x",
      "private_key_id":"x","private_key":"-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----\n",
      "client_email":"x@x.iam.gserviceaccount.com","client_id":"1",
      "auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token"}),
)
from fastapi import FastAPI
from app.routers import register_routers
app = FastAPI(title="vanijyaa")
register_routers(app)

@app.get("/healthz")
def healthz(): return {"ok": True}
