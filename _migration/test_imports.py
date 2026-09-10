"""Gate: every module package must import cleanly. Run: python3.12 _migration/test_imports.py"""
import _boot, sys
res = _boot.import_all_modules()
for m, e in res.items():
    print(f"  {'OK  ' if e is None else 'FAIL'}  {m}" + (f"\n          {type(e).__name__}: {str(e)[:140]}" if e else ""))
bad = [m for m, e in res.items() if e]
print(f"\n{len(res)-len(bad)}/{len(res)} modules import cleanly")

# `from app.modules.X import router` must still work for every module that has one.
import importlib
bad_router = []
for m in ["profile", "onboarding", "verification", "deeplink", "safety"]:
    for k in [k for k in list(sys.modules) if k.startswith("app.")]: del sys.modules[k]
    try:
        mod = importlib.import_module("app.modules." + m)
        r = mod.router
        assert hasattr(r, "routes"), f"{m}.router is not a router"
    except Exception as e:
        bad_router.append(f"  {m}: {type(e).__name__}: {str(e)[:100]}")
if bad_router:
    print("FAIL - lazy router export broken:\n" + "\n".join(bad_router)); sys.exit(1)
print("5/5 lazy `from app.modules.X import router` still resolve")
sys.exit(1 if (bad or bad_router) else 0)
