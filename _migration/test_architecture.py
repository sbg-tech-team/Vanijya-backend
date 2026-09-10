"""Architecture gate — the layering rules, enforced.
    python3.12 _migration/test_architecture.py
"""
import os, subprocess, sys

os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
fails = []
def check(label, got, want):
    if got != want: fails.append(f"  {label}\n     got:  {got!r}\n     want: {want!r}")
def files(cmd):
    out = subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()
    return sorted(l.replace("app_new/modules/", "") for l in out.split("\n") if l)

# 1. SQL lives only in data/
check("no db.query outside data/",
      files("grep -rl 'db\\.query' app_new/modules/*/application app_new/modules/*/presentation 2>/dev/null"), [])
check("no raw execute outside data/",
      files("grep -rl 'db\\.execute' app_new/modules/*/application app_new/modules/*/presentation 2>/dev/null"), [])

# 2. the application layer never depends on the delivery mechanism
check("no application -> presentation imports",
      files("grep -rlE '^\\s*from app\\.modules\\.[a-z_]+\\.presentation' app_new/modules/*/application 2>/dev/null"), [])

# 3. the domain layer depends on nothing
check("no framework imports in domain/",
      files("grep -rlE '^\\s*(from|import) (sqlalchemy|fastapi|pydantic|redis|firebase_admin)' app_new/modules/*/domain 2>/dev/null"), [])
check("no data/ imports in domain/",
      files("grep -rlE '^\\s*from app\\.modules\\.[a-z_]+\\.data' app_new/modules/*/domain 2>/dev/null"), [])

# 4. no dead scaffolding
check("no 0-byte stub files",
      files("find app_new -name '*.py' -size 0 -not -name '__init__.py'"), [])

# 5. a module of the same name as a package would silently shadow it
shadow = []
for dp, dn, fn in os.walk("app_new"):
    if "__pycache__" in dp: continue
    for f in fn:
        if f.endswith(".py") and os.path.isdir(os.path.join(dp, f[:-3])):
            shadow.append(f"{dp}/{f}")
check("no module shadowed by a same-named package", sorted(shadow), [])

# 6. every repository is behind its interface, fully implemented
sys.path.insert(0, os.path.join(os.getcwd(), "_migration"))
import _boot  # noqa: E402,F401
import importlib  # noqa: E402
REPOS = {
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

print(f"  checked {len(REPOS)} modules")
if fails:
    print(f"FAIL ({len(fails)})\n" + "\n".join(fails)); sys.exit(1)
print("PASS - zero architectural violations: SQL only in data/, no application->presentation, "
      "dependency-free domain, no stubs, no shadowing, all 10 repositories behind interfaces")
