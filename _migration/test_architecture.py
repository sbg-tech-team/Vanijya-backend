"""Architecture gate — the layering rules, enforced.
    python3.12 _migration/test_architecture.py

Rules come from documentation/final_architecture.md §2.3:

    Router        -> use cases only
    Use Case      -> repository interfaces, other use cases, core
    Repository    -> database, external APIs, cache
    Domain        -> nothing

presentation/dependencies.py is the exception to the router rule: it is the
module's composition root, so wiring concrete repositories and adapters there
is its job (§2.2, "dependencies.py # Wire use cases + repos for DI").
"""
import ast, os, subprocess, sys

os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
fails = []
def check(label, got, want):
    if got != want: fails.append(f"  {label}\n     got:  {got!r}\n     want: {want!r}")
def files(cmd):
    out = subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()
    return sorted(l for l in out.split("\n") if l and "__pycache__" not in l)

# 1. SQL lives only in data/
check("no db.query outside data/",
      files("grep -rl --include='*.py' 'db\\.query' app/modules/*/application app/modules/*/presentation 2>/dev/null"), [])
check("no raw execute outside data/",
      files("grep -rl --include='*.py' 'db\\.execute' app/modules/*/application app/modules/*/presentation 2>/dev/null"), [])

# 2. the application layer never depends on the delivery mechanism
check("no application -> presentation imports",
      files("grep -rlE --include='*.py' '^\\s*from app\\.modules\\.[a-z_]+\\.presentation' app/modules/*/application 2>/dev/null"), [])
check("no application -> sqlalchemy imports",
      files("grep -rlE --include='*.py' '^\\s*(from|import) sqlalchemy' app/modules/*/application 2>/dev/null"), [])
check("no application -> fastapi imports",
      files("grep -rlE --include='*.py' '^\\s*(from|import) fastapi' app/modules/*/application 2>/dev/null"), [])

# 3. the domain layer depends on nothing
check("no framework imports in domain/",
      files("grep -rlE --include='*.py' '^\\s*(from|import) (sqlalchemy|fastapi|pydantic|redis|firebase_admin|httpx|boto3)' app/modules/*/domain 2>/dev/null"), [])
check("no data/ imports in domain/",
      files("grep -rlE --include='*.py' '^\\s*from app\\.modules\\.[a-z_]+\\.data' app/modules/*/domain 2>/dev/null"), [])

# 4. the data layer never reaches back up
check("no data -> fastapi imports",
      files("grep -rlE --include='*.py' '^\\s*(from|import) fastapi' app/modules/*/data 2>/dev/null"), [])
check("no data -> presentation imports",
      files("grep -rlE --include='*.py' '^\\s*from app\\.modules\\.[a-z_]+\\.presentation' app/modules/*/data 2>/dev/null"), [])

# 5. routers go through use cases; only dependencies.py may wire concretes
router_reaches = []
for dirpath, _, filenames in os.walk("app/modules"):
    if "__pycache__" in dirpath or not dirpath.endswith("presentation") and "/presentation/" not in dirpath:
        continue
    for f in filenames:
        if not f.endswith(".py") or f == "dependencies.py":
            continue
        fp = os.path.join(dirpath, f)
        tree = ast.parse(open(fp).read())
        for n in ast.walk(tree):
            mod = n.module if isinstance(n, ast.ImportFrom) else None
            if isinstance(n, ast.Import):
                mod = n.names[0].name
            if not mod:
                continue
            if mod.split(".")[0] == "sqlalchemy" or ".data." in mod or mod.endswith(".data"):
                router_reaches.append(f"{fp}:{n.lineno} {mod}")
check("no router -> sqlalchemy / data layer (use dependencies.py)", sorted(router_reaches), [])

# 6. no dead scaffolding
check("no 0-byte stub files",
      files("find app -name '*.py' -size 0 -not -name '__init__.py'"), [])

# 7. a module of the same name as a package would silently shadow it
shadow = []
for dp, dn, fn in os.walk("app"):
    if "__pycache__" in dp: continue
    for f in fn:
        if f.endswith(".py") and os.path.isdir(os.path.join(dp, f[:-3])):
            shadow.append(f"{dp}/{f}")
check("no module shadowed by a same-named package", sorted(shadow), [])

# 8. every repository is behind its interface, fully implemented
sys.path.insert(0, os.path.join(os.getcwd(), "_migration"))
import _boot  # noqa: E402,F401
import importlib  # noqa: E402
REPOS = {
    "calling": ("CallingRepository", "ICallingRepository"),
    "chat": ("ChatRepository", "IChatRepository"),
    "connections": ("ConnectionsRepository", "IConnectionsRepository"),
    "groups": ("GroupsRepository", "IGroupsRepository"),
    "post": ("PostRepository", "IPostRepository"),
    "news": ("NewsRepository", "INewsRepository"),
    "profile": ("ProfileRepository", "IProfileRepository"),
    "safety": ("SafetyRepository", "ISafetyRepository"),
    "deeplink": ("DeepLinkRepository", "IDeepLinkRepository"),
    "verification": ("VerificationRepository", "IVerificationRepository"),
    "onboarding": ("OnboardingRepository", "IOnboardingRepository"),
}
for mod, (impl, iface) in REPOS.items():
    try:
        C = getattr(importlib.import_module(f"app.modules.{mod}.data.repository"), impl)
        I = getattr(importlib.import_module(f"app.modules.{mod}.domain.interfaces.repository"), iface)
        check(f"{mod}: {impl} implements {iface}", issubclass(C, I), True)
        check(f"{mod}: no unimplemented abstract methods", sorted(C.__abstractmethods__), [])
    except Exception as e:
        fails.append(f"  {mod}: {type(e).__name__}: {str(e)[:120]}")

# 9. no unauthenticated endpoints except the public share links
try:
    from fastapi.routing import APIRoute
    PUBLIC = {"/share/post/{post_id}", "/share/news/{article_id}", "/share/user/{profile_id}"}
    def _flat(d):
        out = [d]
        for x in d.dependencies: out += _flat(x)
        return out
    from app.routers import register_routers as _rr
    from fastapi import FastAPI as _FA
    _probe = _FA(); _rr(_probe); _probe.openapi()
    unauth = set()
    import app.routers as _routers_mod
    for _mod_name in ["app.modules.post.presentation.recommendation_router",
                      "app.modules.post.presentation.taste_router",
                      "app.modules.news.presentation.router",
                      "app.modules.post.presentation.router",
                      "app.modules.groups.presentation.router",
                      "app.modules.chat.presentation.router",
                      "app.modules.calling.presentation.router",
                      "app.modules.safety.presentation.router",
                      "app.modules.deeplink.presentation.router",
                      "app.modules.profile.presentation.router",
                      "app.modules.verification.presentation.router",
                      "app.modules.onboarding.presentation.router"]:
        _m = importlib.import_module(_mod_name)
        _seen = set()
        for _attr in dir(_m):
            _r = getattr(_m, _attr)
            if not hasattr(_r, "routes") or id(_r) in _seen: continue
            _seen.add(id(_r))
            for _rt in _r.routes:
                if not isinstance(_rt, APIRoute): continue
                _names = {getattr(d.call, "__name__", "") for d in _flat(_rt.dependant)}
                if not any(("current" in n) or ("onboarding" in n) or ("profile_context" in n) for n in _names):
                    unauth.add(_rt.path)
    check("no unauthenticated endpoints beyond the public share links",
          sorted(unauth - PUBLIC), [])
except Exception as e:
    fails.append(f"  auth scan: {type(e).__name__}: {str(e)[:200]}")

# 10. best-effort side effects must not swallow failures silently
import ast as _ast
_silent = []
for _dp, _, _fns in os.walk("app"):
    if "__pycache__" in _dp: continue
    for _f in _fns:
        if not _f.endswith(".py"): continue
        _fp = os.path.join(_dp, _f)
        try: _t = _ast.parse(open(_fp).read())
        except SyntaxError: continue
        for _n in _ast.walk(_t):
            if not isinstance(_n, _ast.ExceptHandler) or len(_n.body) != 1: continue
            if not isinstance(_n.body[0], _ast.Pass): continue
            # a broad `except Exception: pass` hides data loss; narrow ones are control flow
            _typ = _n.type
            _name = getattr(_typ, "id", None) or getattr(_typ, "attr", None)
            if _name in ("Exception", "BaseException"):
                _silent.append(f"{_fp}:{_n.lineno}")
# app/core/monitoring.py is the one legitimate case: the monitoring layer must
# never raise or log from its own failure path.
_silent = [x for x in _silent if not x.startswith("app/core/monitoring.py")]
check("no bare `except Exception: pass` (log it instead)", sorted(_silent), [])

# 11. cross-layer call sites actually bind (a silent TypeError here meant no post
#     was ever indexed — see tests/test_post_indexing.py)
try:
    import inspect as _inspect
    from app.modules.post.recommendation import service as _rec
    _inspect.signature(_rec.index_post).bind(
        repo=None, post_id=1, commodity_id=1, target_role_ids=None,
        lat=0.0, lon=0.0, category_id=1, commodity_quantity=1.0)
    _inspect.signature(_rec.remove_post_index).bind(repo=None, post_id=1)
    check("index_post / remove_post_index accept what their callers pass", True, True)
except Exception as e:
    fails.append(f"  indexing call sites: {type(e).__name__}: {str(e)[:200]}")

# 12. every registered router still resolves (catches a broken DI rewire)
try:
    from fastapi import FastAPI
    from app.routers import register_routers
    _app = FastAPI()
    register_routers(_app)
    paths = _app.openapi()["paths"]
    check("all routers register", len(paths) > 0, True)
    print(f"  {sum(len(v) for v in paths.values())} endpoints across {len(paths)} paths")
except Exception as e:
    fails.append(f"  router registration: {type(e).__name__}: {str(e)[:200]}")

print(f"  checked {len(REPOS)} modules")
if fails:
    print(f"FAIL ({len(fails)})\n" + "\n".join(fails)); sys.exit(1)
print("PASS - zero architectural violations: SQL only in data/, framework-free application "
      "layer, dependency-free domain, data never reaches up, routers go through use cases, "
      "no unauthenticated endpoints, no silently swallowed failures, indexing call sites bind, "
      f"no stubs, no shadowing, all {len(REPOS)} repositories behind interfaces")
