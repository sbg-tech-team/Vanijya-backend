"""Whole-app wiring gate: build the real FastAPI app and assert every app_old
endpoint is reachable, with the news route-order conflict resolved correctly.
    python3.12 _migration/test_app_routes.py
"""
import _boot  # noqa: F401
import inspect, json, re, sys

from fastapi import FastAPI

from app.routers import register_routers

app = FastAPI()
names = register_routers(app)
routes = [r for r in app.routes if hasattr(r, "methods") and hasattr(r, "path")]

fails = []
def check(label, got, want):
    if got != want: fails.append(f"  {label}\n     got:  {got!r}\n     want: {want!r}")

norm = lambda p: re.sub(r"\{[^}]+\}", "{}", p)
have = {f"{m} {norm(r.path)}" for r in routes for m in r.methods if m != "HEAD"}

old = json.load(open("old.json"))["endpoints"]
want = sorted({f'{e["method"]} {norm(e["full"])}' for e in old})
missing = [p for p in want if p not in have]
check("every app_old endpoint is reachable on the real app", missing, [])
check("all routers registered", len(names), 14)

# --- news: no compat/native split anymore -------------------------------------
# The news module was rebuilt to answer app_old's exact paths natively (GNews +
# Groq behavior ported straight into the Clean Architecture skeleton, see
# app/modules/news/), so there is exactly one GET /news/feed route now, not a
# compat-vs-native pair.
feed = [r for r in routes if r.path == "/news/feed" and "GET" in r.methods]
check("exactly one /news/feed route (no compat split)", len(feed), 1)
params = set(inspect.signature(feed[0].endpoint).parameters) if feed else set()
check("it takes app_old's query params", {"limit", "cursor_article_id"} <= params, True)

# --- the admin router is easy to forget --------------------------------------
for p in ["/news/admin/ingest", "/news/admin/enrich", "/news/admin/stats"]:
    check(f"{p} registered", any(r.path == p for r in routes), True)

# --- ordering traps: a literal path must be declared before its {id} sibling --
paths = [r.path for r in routes]
for literal, param in [("/chat/groups", "/chat/groups/{group_id}/messages"),
                       ("/api/v1/groups/view", "/api/v1/groups/{group_id}")]:
    if literal in paths and param in paths:
        check(f"{literal} declared before {param}",
              paths.index(literal) < paths.index(param), True)

print(f"  {len(routes)} routes across {len(names)} routers; {len(want)} app_old endpoints checked")
if fails:
    print(f"FAIL ({len(fails)})\n" + "\n".join(fails)); sys.exit(1)
print("PASS - real app wiring: every app_old endpoint reachable, news answers app_old's paths natively, admin router registered")
