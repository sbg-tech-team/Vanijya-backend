"""Live-database end-to-end tests — real SQL, no fakes.

Every other gate stubs the repository. This one runs the actual queries against a
real Postgres built from app_new's models, which is the only way to catch a wrong
column name, a broken join or a bad relationship.
    sh _migration/test_schema.sh && python3.12 _migration/test_live_db.py
"""
import _db  # noqa: F401  (sets DSN + stubs BEFORE app imports)
import sys
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

import _seed
from app.dependencies import CurrentUser, get_current_user, get_current_user_id, get_db

_db.import_all_models(); _db.create_schema()
_session = _db.SessionTesting()
IDS = _seed.seed(_session)
ME, OTHER = IDS["me"], IDS["other"]

fails = []
def check(label, got, want):
    if got != want: fails.append(f"  {label}\n     got:  {got!r}\n     want: {want!r}")

def client(*routers, repo_overrides=None):
    app = FastAPI()
    for r in routers: app.include_router(r)
    def _db_dep():
        s = _db.SessionTesting()
        try: yield s
        finally: s.close()
    app.dependency_overrides[get_db] = _db_dep
    app.dependency_overrides[get_current_user_id] = lambda: ME["user_id"]
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=ME["user_id"], profile_id=ME["profile_id"])
    for k, v in (repo_overrides or {}).items(): app.dependency_overrides[k] = v
    return TestClient(app)

# ─────────────────────────── safety (real SQL) ───────────────────────────────
from app.modules.safety.presentation.router import router as safety_router
c = client(safety_router)
t = str(OTHER["user_id"])
r = c.post(f"/safety/block/{t}")
check("[safety] block 200", r.status_code, 200)
check("[safety] block body", r.json(), {"status": "blocked", "blocked_id": t})
check("[safety] re-block 409", c.post(f"/safety/block/{t}").status_code, 409)
r = c.get("/safety/blocked", params={"page": 1, "limit": 20}).json()
check("[safety] list keys", sorted(r), ["blocked", "limit", "page", "total"])
check("[safety] total", r["total"], 1)
# the Profile outerjoin app_new had dropped — proves it really joins
check("[safety] joined name", r["blocked"][0]["name"], "Bob")
check("[safety] joined avatar", r["blocked"][0]["avatar_url"], "http://img/Bob.png")
check("[safety] status true", c.get(f"/safety/block/status/{t}").json()["is_blocked"], True)
check("[safety] unblock", c.delete(f"/safety/block/{t}").json()["status"], "unblocked")
check("[safety] unblock twice 404", c.delete(f"/safety/block/{t}").status_code, 404)
r = c.post("/safety/report", json={"target_type": "user", "target_id": t, "reason": "spam"})
check("[safety] report 200", r.status_code, 200)
check("[safety] report keys", sorted(r.json()),
      ["created_at", "id", "reason", "status", "target_id", "target_type"])
check("[safety] dup report 409",
      c.post("/safety/report", json={"target_type": "user", "target_id": t, "reason": "spam"}).status_code, 409)
check("[safety] reports page", sorted(c.get("/safety/reports").json()),
      ["limit", "page", "reports", "total"])

# ─────────────────────────── deeplink (real SQL) ─────────────────────────────
from app.modules.deeplink.presentation.router import router as dl_router
c = client(dl_router)
r = c.get(f"/share/post/{IDS['post_id']}")
check("[deeplink] post 200", r.status_code, 200)
d = r.json()["data"]
check("[deeplink] deep_link", d["deep_link"], f"vanijyaa://post/{IDS['post_id']}")
check("[deeplink] title uses author", d["title"], "Post by Alice")
check("[deeplink] image from array", d["image_url"], "http://img/p1.png")
r = c.get(f"/share/user/{ME['profile_id']}").json()["data"]
check("[deeplink] user desc joins business", r["description"], "Alice Traders · Pune")
check("[deeplink] missing post 404", c.get("/share/post/99999").status_code, 404)
r = c.get(f"/share/news/{IDS['article_id']}")
check("[deeplink] news 200", r.status_code, 200)
check("[deeplink] news title", r.json()["data"]["title"], "Wheat prices climb")

# ─────────────────────── news compat: app_old bodies ─────────────────────────
from app.modules.news.presentation.compat_router import router as news_compat
c = client(news_compat)
r = c.get("/news/feed", params={"limit": 10})
check("[news] feed 200", r.status_code, 200)
body = r.json()["data"]
check("[news] feed is a NewsFeedPage", sorted(body), ["articles", "next_cursor"])
if body["articles"]:
    card = body["articles"][0]
    check("[news] NewsCard keys", sorted(card),
          ["article_id", "geo_category", "image_url", "impact_direction", "impact_score",
           "is_government", "is_liked", "is_saved", "like_count", "platform_arrived_at",
           "primary_factor", "share_count", "source_name", "summary_bullets",
           "time_on_platform", "title"])
    check("[news] source joined", card["source_name"], "Reuters")
    check("[news] time_on_platform format", card["time_on_platform"].endswith("h"), True)
aid = str(IDS["article_id"])
r = c.post(f"/news/interactions/like/{aid}")
check("[news] like body", r.json()["data"], {"article_id": aid, "is_liked": True})
r = c.post(f"/news/interactions/save/{aid}")
check("[news] save body", r.json()["data"], {"article_id": aid, "is_saved": True})
r = c.post(f"/news/interactions/share/{aid}", params={"platform": "whatsapp"})
check("[news] share echoes platform", r.json()["data"],
      {"article_id": aid, "platform": "whatsapp"})
check("[news] saved feed shape", sorted(c.get("/news/feed/saved").json()["data"]),
      ["articles", "next_cursor"])
check("[news] saved feed has the saved article",
      [a["article_id"] for a in c.get("/news/feed/saved").json()["data"]["articles"]], [aid])
g = c.get("/news/feed/global").json()["data"]["articles"]
check("[news] global tab only global scope",
      [a["article_id"] for a in g], [str(IDS["global_article_id"])])
dom = c.get("/news/feed/domestic").json()["data"]["articles"]
check("[news] domestic tab excludes global", [a["article_id"] for a in dom], [aid])
gov = c.get("/news/feed/government").json()["data"]["articles"]
check("[news] government tab = cluster 1", [a["article_id"] for a in gov], [aid])
check("[news] article detail is NewsCardDetail",
      "article_url" in c.get(f"/news/articles/{aid}").json()["data"], True)
import datetime
r = c.post("/news/interactions/batch", json={"events": [
    {"article_id": aid, "event_type": "impression",
     "occurred_at": datetime.datetime.now(datetime.timezone.utc).isoformat()},
    {"article_id": aid, "event_type": "impression",
     "occurred_at": (datetime.datetime.now(datetime.timezone.utc)
                     - datetime.timedelta(hours=5)).isoformat()},
    {"article_id": "11111111-1111-1111-1111-111111111111", "event_type": "impression",
     "occurred_at": datetime.datetime.now(datetime.timezone.utc).isoformat()},
]})
check("[news] batch 200", r.status_code, 200)
check("[news] batch drops stale + unknown", r.json()["data"], {"accepted": 1, "dropped": 2})

# ─────────────────────── news admin (real counts) ────────────────────────────
from app.modules.news.presentation.compat_router import admin_router
c = client(admin_router)
st = c.get("/news/admin/stats").json()["data"]
check("[news] stats keys", sorted(st), ["enriched", "failed", "pending", "total"])
check("[news] stats total", st["total"], 2)
check("[news] stats enriched", st["enriched"], 2)

# ─────────────────────── verification (real SQL) ─────────────────────────────
from app.modules.verification.presentation.router import router as ver_router
from app.modules.verification.presentation.dependencies import get_document_verifier
from app.modules.verification.domain.interfaces.verifier import IDocumentVerifier
class OkVerifier(IDocumentVerifier):
    def verify(self, document_type, document_number, **kw): return "surepass", {"ok": True}
c = client(ver_router, repo_overrides={get_document_verifier: lambda: OkVerifier()})
r = c.post("/verification/kyc/pan", json={"id_number": "ABCDE1234F", "name": "Alice", "dob": "1990-01-01"})
check("[verification] pan 200", r.status_code, 200)
check("[verification] pan verified", r.json()["data"]["status"], "verified")
s2 = _db.SessionTesting()
from app.modules.profile.data.models import Profile
check("[verification] profile flag really persisted",
      s2.query(Profile).filter(Profile.id == ME["profile_id"]).first().is_user_verified, True)
s2.close()
st = c.get("/verification/status").json()
check("[verification] status kyc", st["kyc"]["status"], "verified")
check("[verification] status kyb", st["kyb"]["status"], "not_submitted")

if fails:
    print(f"FAIL ({len(fails)})\n" + "\n".join(fails)); sys.exit(1)
print("PASS - live Postgres: safety, deeplink, news compat bodies, admin, verification "
      "all execute real SQL and return app_old's shapes")
