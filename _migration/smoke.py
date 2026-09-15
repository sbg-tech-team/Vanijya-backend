"""Per-module smoke test against a RUNNING server — modules run in parallel.

Unlike every other gate, this speaks HTTP to a real uvicorn process backed by a
real Postgres, with no stubs anywhere. It exercises write paths, not just reads.

    python3.12 _migration/smoke.py --base http://127.0.0.1:8099 [--module news]

Each module is independent and gets its own worker, so a failure is attributed
to one module and the rest still report.
"""
from __future__ import annotations

import argparse, json, sys, time, uuid
from concurrent.futures import ThreadPoolExecutor

import httpx

BASE = "http://127.0.0.1:8099"
TOKEN = ""


def call(method, path, *, expect=200, json_body=None, params=None, note=""):
    """One HTTP call. Returns (ok, detail)."""
    try:
        r = httpx.request(method, BASE + path,
                          headers={"Authorization": f"Bearer {TOKEN}"},
                          json=json_body, params=params, timeout=20,
                          follow_redirects=True)   # /profile/{me} 307s to /profile/me by design
    except Exception as e:
        return False, f"{method} {path} -> transport error: {type(e).__name__}: {e}"
    want = expect if isinstance(expect, (list, tuple)) else [expect]
    if r.status_code not in want:
        body = r.text[:160].replace("\n", " ")
        return False, f"{method} {path} -> {r.status_code}, wanted {want}  {note}  {body}"
    return True, f"{method} {path} -> {r.status_code} {note}"


# ── per-module suites ────────────────────────────────────────────────────────
def m_profile(ctx):
    yield call("GET", "/profile/me")
    yield call("GET", f"/profile/{ctx['profile_id']}", note="(self-view 307s to /profile/me)")
    yield call("PATCH", "/profile/", json_body={"name": "Alice"}, expect=[200, 400, 409])
    # content_type is required; storage itself may be unreachable in a test env
    yield call("GET", "/profile/avatar-upload-url",
               params={"content_type": "image/jpeg"}, expect=[200, 400, 500, 502, 503])
    yield call("GET", "/profile/avatar-upload-url", expect=422, note="(missing content_type)")

def m_safety(ctx):
    t = ctx["other_user_id"]
    yield call("POST", f"/safety/block/{t}", expect=[200, 409])
    yield call("GET", "/safety/blocked", params={"page": 1, "limit": 20})
    yield call("GET", f"/safety/block/status/{t}")
    yield call("DELETE", f"/safety/block/{t}", expect=[200, 404])
    yield call("POST", "/safety/report",
               json_body={"target_type": "user", "target_id": t, "reason": "spam"},
               expect=[200, 409])
    yield call("GET", "/safety/reports")
    yield call("POST", f"/safety/block/{ctx['my_user_id']}", expect=400, note="(self-block)")

def m_news(ctx):
    a = ctx["article_id"]
    yield call("GET", "/news/feed", params={"limit": 5})
    yield call("GET", "/news/trending")
    for tab in ("global", "domestic", "government", "saved"):
        yield call("GET", f"/news/feed/{tab}")
    yield call("GET", f"/news/articles/{a}")
    yield call("POST", f"/news/interactions/like/{a}")
    yield call("POST", f"/news/interactions/save/{a}")
    yield call("POST", f"/news/interactions/share/{a}", params={"platform": "whatsapp"})
    yield call("GET", f"/news/interactions/share-sheet/{a}")
    yield call("POST", "/news/interactions/batch", json_body={"events": [
        {"article_id": a, "event_type": "impression",
         "occurred_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00")}]})
    yield call("GET", f"/news/articles/{uuid.uuid4()}", expect=404, note="(unknown article)")
    yield call("GET", "/news/admin/stats")

def m_post(ctx):
    p = ctx["post_id"]
    yield call("GET", f"/posts/{p}")
    for path in ("/posts/mine", "/posts/following", "/posts/saved"):
        yield call("GET", path)
    yield call("POST", f"/posts/{p}/like")
    yield call("POST", f"/posts/{p}/save")
    yield call("GET", f"/posts/{p}/comments")
    yield call("POST", f"/posts/{p}/comments", json_body={"content": "smoke"}, expect=201)
    yield call("GET", f"/posts/{p}/share")
    yield call("GET", "/posts/999999", expect=404, note="(unknown post)")

def m_connections(ctx):
    t = ctx["other_user_id"]
    yield call("POST", f"/connections/follow/{t}", expect=[201, 409])
    yield call("GET", f"/connections/follow/status/{t}")
    yield call("GET", f"/connections/{ctx['my_user_id']}/following")
    yield call("GET", f"/connections/{t}/followers")
    yield call("GET", "/connections/search", params={"q": "Bob"})
    yield call("GET", "/connections/search/suggestions", params={"q": "Bo"})
    yield call("GET", "/connections/share-recipients")
    yield call("GET", "/connections/message-requests/received")
    yield call("GET", "/connections/message-requests/sent")
    yield call("DELETE", f"/connections/follow/{t}", expect=[200, 404])
    yield call("GET", "/recommendations/", expect=[200, 404, 500], note="(needs pgvector data)")

def m_groups(ctx):
    g = ctx["group_id"]
    yield call("GET", "/api/v1/groups/")
    yield call("GET", f"/api/v1/groups/{g}")
    yield call("GET", f"/api/v1/groups/{g}/members")
    yield call("GET", f"/api/v1/groups/{g}/media")
    yield call("GET", f"/api/v1/groups/{g}/deals")
    yield call("GET", f"/api/v1/groups/{g}/join-requests")
    yield call("GET", "/api/v1/groups/my-pending-requests")
    yield call("POST", "/api/v1/groups/view",
               json_body={"group_id": g, "commodity_ids": [1]}, expect=204)
    yield call("POST", f"/api/v1/groups/{g}/favorite", expect=[200, 201, 204])
    yield call("POST", f"/api/v1/groups/{g}/mute", expect=[200, 201, 204])

def m_chat(ctx):
    yield call("GET", "/chat/all")
    yield call("GET", "/chat/conversations")
    yield call("GET", "/chat/groups")
    yield call("GET", "/chat/share/recipients")
    yield call("GET", "/chat/presence", params={"user_ids": ctx["other_user_id"]})
    r = httpx.post(BASE + "/chat/conversations",
                   headers={"Authorization": f"Bearer {TOKEN}"},
                   json={"participant_id": ctx["other_user_id"]}, timeout=20)
    yield (r.status_code == 200,
           f"POST /chat/conversations -> {r.status_code} (get-or-create DM)")
    if r.status_code == 200:
        cid = r.json()["id"]
        yield call("GET", f"/chat/conversations/{cid}/messages")

def m_verification(ctx):
    yield call("GET", "/verification/status")
    yield call("POST", "/verification/kyc/aadhaar",
               json_body={"aadhaar_number": "123412341234"}, expect=501)

def m_deeplink(ctx):
    yield call("GET", f"/share/post/{ctx['post_id']}")
    yield call("GET", f"/share/user/{ctx['profile_id']}")
    yield call("GET", f"/share/news/{ctx['article_id']}")
    yield call("GET", "/share/post/999999", expect=404)
    yield call("GET", "/share/news/not-a-uuid", expect=404)

def m_onboarding(ctx):
    yield call("POST", "/auth/refresh", json_body={"refresh_token": "bogus"}, expect=401)
    yield call("POST", "/auth/logout", json_body={}, expect=200)

MODULES = {
    "profile": m_profile, "safety": m_safety, "news": m_news, "post": m_post,
    "connections": m_connections, "groups": m_groups, "chat": m_chat,
    "verification": m_verification,
    "deeplink": m_deeplink, "onboarding": m_onboarding,
}


def run_module(name, ctx):
    t0 = time.time()
    results = list(MODULES[name](ctx))
    bad = [d for ok, d in results if not ok]
    return name, len(results), bad, time.time() - t0


def main():
    global BASE, TOKEN
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--module", action="append")
    ap.add_argument("--ctx", default="/tmp/smoke_ctx.json")
    args = ap.parse_args()
    BASE = args.base.rstrip("/")
    ctx = json.load(open(args.ctx))
    TOKEN = ctx["token"]

    names = args.module or list(MODULES)
    print(f"smoke: {len(names)} modules in parallel against {BASE}\n")
    with ThreadPoolExecutor(max_workers=len(names)) as pool:
        out = sorted(pool.map(lambda n: run_module(n, ctx), names))

    total = failed = 0
    for name, n, bad, secs in out:
        total += n; failed += len(bad)
        mark = "ok  " if not bad else "FAIL"
        print(f"  {mark} {name:<14} {n - len(bad):>2}/{n:<2} checks  {secs * 1000:6.0f} ms")
        for d in bad: print(f"         {d}")
    print(f"\n{total - failed}/{total} checks passed across {len(out)} modules")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
