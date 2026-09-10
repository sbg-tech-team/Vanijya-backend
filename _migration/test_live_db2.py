"""Live-DB regression net for post / connections / groups — the modules whose
repositories are about to be extracted. Real SQL, real responses.
Captures a BASELINE so the refactor can be proved behaviour-preserving.
    python3.12 _migration/test_live_db2.py [--save-baseline]
"""
import _db  # noqa: F401  (env + stubs before app imports)
import json, os, sys

import redis as redis_lib
from fastapi import FastAPI
from fastapi.testclient import TestClient

import _seed
from app.dependencies import (
    CurrentUser, get_current_profile_id, get_current_user, get_current_user_id, get_db)

_db.import_all_models(); _db.create_schema()
IDS = _seed.seed(_db.SessionTesting())
ME, OTHER = IDS["me"], IDS["other"]

fails = []
def check(label, got, want):
    if got != want: fails.append(f"  {label}\n     got:  {got!r}\n     want: {want!r}")


class FakeRedis:
    """Enough Redis for the endpoints under test; taste writes are fail-silent."""
    def __init__(self): self.store = {}
    def pipeline(self, *a, **k): return self
    def execute(self, *a, **k): return []
    def hincrbyfloat(self, *a, **k): return 0.0
    def hset(self, *a, **k): return 0
    def hgetall(self, *a, **k): return {}
    def expire(self, *a, **k): return True
    def exists(self, *a, **k): return 0
    def sadd(self, *a, **k): return 0
    def smembers(self, *a, **k): return set()
    def srem(self, *a, **k): return 0
    def delete(self, *a, **k): return 0
    def get(self, *a, **k): return None
    def set(self, *a, **k): return True
    def keys(self, *a, **k): return []
    def hget(self, *a, **k): return None
    def zadd(self, *a, **k): return 0
    def zrange(self, *a, **k): return []


def client(*routers):
    from app.core.redis_client import get_redis
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
    app.dependency_overrides[get_current_profile_id] = lambda: ME["profile_id"]
    app.dependency_overrides[get_redis] = lambda: FakeRedis()
    return TestClient(app, raise_server_exceptions=False)


snap = {}
def record(name, resp):
    """Store status + shape so the pre/post-refactor comparison is exact."""
    try: body = resp.json()
    except Exception: body = None
    def shape(v):
        if isinstance(v, dict): return {k: shape(x) for k, x in sorted(v.items())}
        if isinstance(v, list): return [shape(v[0])] if v else []
        return type(v).__name__
    snap[name] = {"status": resp.status_code, "shape": shape(body)}
    return body


# ─────────────────────────────── post ────────────────────────────────────────
from app.modules.post.presentation.router import router as post_router
c = client(post_router)
pid = IDS["post_id"]
b = record("post.get", c.get(f"/posts/{pid}"))
check("[post] GET /posts/{id} 200", snap["post.get"]["status"], 200)
for path in ["/posts/mine", "/posts/following", "/posts/saved"]:
    r = c.get(path); record(f"post.{path}", r)
    check(f"[post] GET {path} 200", r.status_code, 200)
r = c.post(f"/posts/{pid}/like"); record("post.like", r)
check("[post] like 200", r.status_code, 200)
r = c.post(f"/posts/{pid}/save"); record("post.save", r)
check("[post] save 200", r.status_code, 200)
r = c.get(f"/posts/{pid}/comments"); record("post.comments", r)
check("[post] comments 200", r.status_code, 200)
r = c.post(f"/posts/{pid}/comments", json={"content": "nice"}); record("post.comment_create", r)
check("[post] create comment 201", r.status_code, 201)
check("[post] missing post 404", c.get("/posts/999999").status_code, 404)
r = c.get(f"/posts/{pid}/share"); record("post.share_sheet", r)
check("[post] share sheet not 5xx", r.status_code < 500, True)
r = c.patch(f"/posts/{pid}", json={"caption": "updated caption"}); record("post.update", r)
check("[post] update not 5xx", r.status_code < 500, True)
r = c.post(f"/posts/{pid}/record-share", json={}); record("post.record_share", r)
check("[post] record-share not 5xx", r.status_code < 500, True)
r = c.post(f"/posts/{pid}/close"); record("post.close", r)
check("[post] close not 5xx", r.status_code < 500, True)
r = c.post("/posts/", json={"title": "T", "caption": "C", "category_id": 1,
                            "commodity_id": 1, "image_urls": []})
record("post.create", r)
check("[post] create not 5xx", r.status_code < 500, True)

# ──────────────────────────── connections ────────────────────────────────────
from app.modules.connections.presentation.router import (
    connections_router, recommendations_router)
c = client(connections_router, recommendations_router)
t = str(OTHER["user_id"])
r = c.post(f"/connections/follow/{t}"); record("conn.follow", r)
check("[connections] follow 201", r.status_code, 201)
r = c.get(f"/connections/follow/status/{t}"); record("conn.follow_status", r)
check("[connections] follow status 200", r.status_code, 200)
r = c.get(f"/connections/{ME['user_id']}/following"); record("conn.following", r)
check("[connections] following 200", r.status_code, 200)
r = c.get(f"/connections/{t}/followers"); record("conn.followers", r)
check("[connections] followers 200", r.status_code, 200)
r = c.get("/connections/search", params={"q": "Bob"}); record("conn.search", r)
check("[connections] search 200", r.status_code, 200)
r = c.get("/connections/search/suggestions", params={"q": "Bo"}); record("conn.suggest", r)
check("[connections] suggestions 200", r.status_code, 200)
r = c.get("/connections/message-requests/received"); record("conn.mr_recv", r)
check("[connections] msg requests received 200", r.status_code, 200)
r = c.delete(f"/connections/follow/{t}"); record("conn.unfollow", r)
check("[connections] unfollow 200", r.status_code, 200)

# ─────────────────────────────── groups ──────────────────────────────────────
from app.modules.groups.presentation.router import router as groups_router
c = client(groups_router)
r = c.get("/api/v1/groups/"); record("grp.list", r)
check("[groups] list 200", r.status_code, 200)
r = c.post("/api/v1/groups/view",
           json={"group_id": "11111111-1111-1111-1111-111111111111", "commodity_ids": [1]})
record("grp.view", r)
check("[groups] view signal 204", r.status_code, 204)
r = c.get("/api/v1/groups/my-pending-requests"); record("grp.pending", r)
check("[groups] my-pending-requests 200", r.status_code, 200)
gid = str(IDS["group_id"])
for path, name in [(f"/api/v1/groups/{gid}", "grp.detail"),
                   (f"/api/v1/groups/{gid}/members", "grp.members"),
                   (f"/api/v1/groups/{gid}/posts", "grp.posts"),
                   (f"/api/v1/groups/{gid}/media", "grp.media"),
                   (f"/api/v1/groups/{gid}/deals", "grp.deals"),
                   (f"/api/v1/groups/{gid}/join-requests", "grp.joinreqs")]:
    r = c.get(path); record(name, r)
    check(f"[groups] GET {path.split(gid)[-1] or '/{id}'} not 5xx", r.status_code < 500, True)
r = c.post("/api/v1/groups/", json={
    "name": "New Rice Group", "description": "d", "commodity": ["rice"],
    "target_roles": ["trader"], "region_market": "Nashik", "accessibility": "public"})
record("grp.create", r)
check("[groups] create not 5xx", r.status_code < 500, True)
r = c.patch(f"/api/v1/groups/{gid}", json={"description": "updated"})
record("grp.update", r)
check("[groups] update not 5xx", r.status_code < 500, True)
r = c.post(f"/api/v1/groups/{gid}/favorite"); record("grp.fav", r)
check("[groups] favorite not 5xx", r.status_code < 500, True)
r = c.post(f"/api/v1/groups/{gid}/mute"); record("grp.mute", r)
check("[groups] mute not 5xx", r.status_code < 500, True)

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "baseline.json")
if "--save-baseline" in sys.argv:
    json.dump(snap, open(BASE, "w"), indent=1, sort_keys=True)
    print(f"baseline saved: {len(snap)} responses -> {BASE}")
elif os.path.exists(BASE):
    old = json.load(open(BASE))
    drift = {k: (old.get(k), snap[k]) for k in snap if old.get(k) != snap[k]}
    drift.update({k: (old[k], None) for k in old if k not in snap})
    for k, (a, b_) in sorted(drift.items()):
        fails.append(f"  BASELINE DRIFT {k}\n     before: {a}\n     after:  {b_}")
    print(f"  compared {len(snap)} responses against the pre-refactor baseline")

if fails:
    print(f"FAIL ({len(fails)})\n" + "\n".join(fails[:20])); sys.exit(1)
print(f"PASS - live DB: post / connections / groups, {len(snap)} responses recorded")
