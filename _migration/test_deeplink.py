"""Deeplink contract test — locks app_old's exact share_text bytes and envelope.
    python3.12 _migration/test_deeplink.py
"""
import _boot  # noqa: F401
import sys
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.deeplink.domain.entities import ShareArticle, SharePost, ShareProfile
from app.modules.deeplink.domain.interfaces.repository import IDeepLinkRepository
from app.modules.deeplink.presentation.dependencies import get_deeplink_repo
from app.modules.deeplink.presentation.router import router

STORE = "https://play.google.com/store/apps/details?id=com.vanijyaa.app"
AID = UUID("33333333-3333-3333-3333-333333333333")
LONG = "x" * 130


class FakeRepo(IDeepLinkRepository):
    def __init__(self):
        self.posts, self.articles, self.profiles = {}, {}, {}
    def get_post(self, post_id):        return self.posts.get(post_id)
    def get_article(self, article_id):  return self.articles.get(article_id)
    def get_profile(self, profile_id):  return self.profiles.get(profile_id)


repo = FakeRepo()
repo.posts[7]  = SharePost(7, "Hello world", "http://img/1.png", "Alice")
repo.posts[8]  = SharePost(8, None, None, None)            # no caption, no author
repo.posts[9]  = SharePost(9, LONG, None, "Alice")         # truncation
repo.articles[AID] = ShareArticle("Wheat up", "Prices rose", "http://img/n.png")
repo.profiles[3] = ShareProfile(3, "Bob", "http://img/a.png", "Acme", "Pune")
repo.profiles[4] = ShareProfile(4, "Carol", None, None, None)   # no business

app = FastAPI(); app.include_router(router)
app.dependency_overrides[get_deeplink_repo] = lambda: repo
c = TestClient(app)

fails = []
def check(label, got, want):
    if got != want:
        fails.append(f"  {label}\n     got:  {got!r}\n     want: {want!r}")

check("route set",
      sorted(f"{sorted(r.methods)[0]} {r.path}" for r in router.routes),
      ["GET /share/news/{article_id}", "GET /share/post/{post_id}", "GET /share/user/{profile_id}"])

# --- envelope: ok(...) wrapper must be intact --------------------------------
r = c.get("/share/post/7")
check("post 200", r.status_code, 200)
check("envelope keys", sorted(r.json()), ["data", "message", "success"])
check("envelope msg", (r.json()["success"], r.json()["message"]), (True, "Share link generated"))
check("data keys", sorted(r.json()["data"]),
      ["deep_link", "description", "image_url", "share_text", "title"])

# --- share_text byte-for-byte (app_old f-strings) ----------------------------
d = r.json()["data"]
check("post deep_link", d["deep_link"], "vanijyaa://post/7")
check("post title", d["title"], "Post by Alice")
check("post image", d["image_url"], "http://img/1.png")
check("post share_text", d["share_text"],
      f"Alice shared a post on Vanijyaa\n\nHello world\n\nOpen in app: vanijyaa://post/7\nDownload Vanijyaa: {STORE}")

d = c.get("/share/post/8").json()["data"]
check("post no-caption fallback name", d["title"], "Post by Vanijyaa User")
check("post no-caption share_text", d["share_text"],
      f"Vanijyaa User shared a post on Vanijyaa\n\n\n\nOpen in app: vanijyaa://post/8\nDownload Vanijyaa: {STORE}")

d = c.get("/share/post/9").json()["data"]
check("caption truncated at 120 + ellipsis", d["description"], "x" * 120 + "...")

d = c.get(f"/share/news/{AID}").json()["data"]
check("news share_text", d["share_text"],
      f"Wheat up\n\nPrices rose\n\nOpen in Vanijyaa: vanijyaa://news/{AID}\nDownload Vanijyaa: {STORE}")
check("news title", d["title"], "Wheat up")

d = c.get("/share/user/3").json()["data"]
check("user description joins with ' · '", d["description"], "Acme · Pune")
check("user share_text", d["share_text"],
      f"Connect with Bob on Vanijyaa\n\nAcme · Pune\nOpen in app: vanijyaa://user/3\nDownload Vanijyaa: {STORE}")

# profile with no Business row: app_old raised AttributeError -> 500.
# Intentional deviation: guarded, returns the documented shape.
r = c.get("/share/user/4")
check("no-business -> 200 not 500", r.status_code, 200)
check("no-business description", r.json()["data"]["description"], None)
check("no-business share_text", r.json()["data"]["share_text"],
      f"Connect with Carol on Vanijyaa\n\nOpen in app: vanijyaa://user/4\nDownload Vanijyaa: {STORE}")

# --- 404s --------------------------------------------------------------------
check("missing post -> 404", c.get("/share/post/999").status_code, 404)
check("missing post detail", c.get("/share/post/999").json()["detail"], "Post not found")
check("missing article -> 404",
      c.get("/share/news/44444444-4444-4444-4444-444444444444").status_code, 404)
check("malformed uuid -> 404", c.get("/share/news/not-a-uuid").status_code, 404)
check("malformed uuid detail", c.get("/share/news/not-a-uuid").json()["detail"], "Invalid article ID")
check("missing profile -> 404", c.get("/share/user/999").status_code, 404)
check("non-int post id -> 422", c.get("/share/post/abc").status_code, 422)

if fails:
    print("FAIL\n" + "\n".join(fails)); sys.exit(1)
print("PASS - deeplink contract matches app_old (3 routes, exact share_text, envelope, 404s)")
