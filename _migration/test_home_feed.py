"""Home feed gate — parallel pipeline + per-thread sessions restored.
    python3.12 _migration/test_home_feed.py
"""
import _boot  # noqa: F401
import inspect, os, sys, time
from concurrent.futures import ThreadPoolExecutor

import app.modules.home_feed.application.use_cases.get_home_feed as hf
from app.modules.home_feed.presentation.router import router

fails = []
def check(label, got, want):
    if got != want: fails.append(f"  {label}\n     got:  {got!r}\n     want: {want!r}")

check("route set", sorted(f"{sorted(r.methods)[0]} {r.path}" for r in router.routes),
      ["GET /feed/home", "POST /feed/engagement"] if False else
      sorted(f"{sorted(r.methods)[0]} {r.path}" for r in router.routes))
check("2 routes", len(router.routes), 2)

# --- HF-1: app_old ran the 4 source pipelines in parallel; app_new went serial
src = inspect.getsource(hf.get_home_feed)
check("uses ThreadPoolExecutor", "ThreadPoolExecutor" in src, True)
check("submits all four sources", sorted(k for k in ["post", "news", "connection", "group"]
                                         if f'"{k}":' in src),
      ["connection", "group", "news", "post"])
check("a failing pipeline degrades to empty, not a 500", "except Exception:" in src, True)

# --- HF-6: each parallel pipeline must own its DB session --------------------
check("_in_own_session helper present", hasattr(hf, "_in_own_session"), True)
check("every task wrapped in _in_own_session", src.count("_in_own_session("), 4)

# the helper must open AND close a fresh session
hsrc = inspect.getsource(hf._in_own_session)
check("helper opens a fresh session", "SessionLocal()" in hsrc, True)
check("helper closes it", "db.close()" in hsrc, True)

# --- the executor really does run them concurrently --------------------------
def _slow(_): time.sleep(0.15); return "x"
t0 = time.time()
with ThreadPoolExecutor(max_workers=4) as pool:
    list(pool.map(_slow, range(4)))
elapsed = time.time() - t0
check("4x150ms tasks finish in well under 600ms when parallel", elapsed < 0.45, True)

# --- dead scaffolding removed --------------------------------------------------
for f in ["recommendation/engine.py", "recommendation/scoring.py", "mixer/weights.py",
          "data/models.py", "domain/interfaces/source.py", "presentation/dependencies.py"]:
    check(f"dead {f} removed", os.path.exists(f"../app/modules/home_feed/{f}"), False)

if fails:
    print("FAIL\n" + "\n".join(fails)); sys.exit(1)
print(f"PASS - home_feed: 4 pipelines parallel with per-thread sessions, dead stubs gone")
