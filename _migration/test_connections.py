"""Connections contract test — 31 routes, amplify restored, dead scaffolding gone.
    python3.12 _migration/test_connections.py
"""
import _boot  # noqa: F401
import os, subprocess, sys

from app.modules.connections.presentation.router import (
    connections_router, recommendations_router)
from app.recommendation.amplify import (
    commodity_boost, commodity_ids_for, get_amplify_weights, write_commodity_signals)
from app.recommendation.session_taste import ActionType

fails = []
def check(label, got, want):
    if got != want: fails.append(f"  {label}\n     got:  {got!r}\n     want: {want!r}")
def count(cmd): return int(subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip() or 0)

# --- amplify was never ported to app_new; 5 imports dangled ------------------
check("amplify.commodity_boost callable", callable(commodity_boost), True)
# app_new had dropped 5 ActionType members; two of them are called by connections,
# so following a user raised AttributeError at runtime.
from app.recommendation.session_taste import SIGNAL_WEIGHTS
for m, v in [("CONNECTION_FOLLOW", "connection_follow"), ("CONNECTION_MSG", "connection_msg"),
             ("GROUP_VIEW", "group_view"), ("GROUP_JOIN", "group_join"),
             ("GROUP_DISMISS", "group_dismiss")]:
    check(f"ActionType.{m} restored", getattr(ActionType, m, None) and ActionType[m].value, v)
    check(f"SIGNAL_WEIGHTS['{v}'] restored", SIGNAL_WEIGHTS.get(v) is not None, True)
check("every ActionType has a SIGNAL_WEIGHTS entry",
      [a.value for a in ActionType if a.value not in SIGNAL_WEIGHTS], [])
check("connection_follow weight matches app_old", SIGNAL_WEIGHTS["connection_follow"], (5.0, 0.0, 4.0))
check("group_dismiss weight matches app_old", SIGNAL_WEIGHTS["group_dismiss"], (0.0, 2.0, 0.0))
check("no app.modules.taste imports remain",
      count("grep -rlE '^\\s*from app\\.modules\\.taste' ../app --include='*.py' | wc -l"), 0)
# dead legacy route modules (unimportable in app_old, never registered in either)
for f in ["routes_connections.py", "routes_recommendations.py", "routes_users.py"]:
    check(f"dead {f} removed",
          os.path.exists(f"../app/modules/connections/presentation/{f}"), False)

# --- amplify's boost maths, ported verbatim from app_old ---------------------
check("no weights -> no boost", commodity_boost({}, [1]), 1.0)
check("no candidate commodities -> no boost", commodity_boost({"1": 5.0}, []), 1.0)
check("unmatched commodity -> no boost", commodity_boost({"9": 5.0}, [1]), 1.0)
check("saturated boost is 1.30x", round(commodity_boost({"1": 99.0}, [1]), 4), 1.30)
check("half of BOOST_REF -> half boost", round(commodity_boost({"1": 1.5}, [1]), 4), 1.15)
check("takes the hottest match, not the sum",
      round(commodity_boost({"1": 1.5, "2": 3.0}, [1, 2]), 4), 1.30)
check("write_commodity_signals is fail-silent on no redis",
      write_commodity_signals(None, 1, "connections", [1], ActionType.CONNECTION_FOLLOW), None)

# --- 31 routes, unchanged from app_old ---------------------------------------
routes = sorted(f"{sorted(r.methods)[0]} {r.path}"
                for r in list(connections_router.routes) + list(recommendations_router.routes))
check("route count", len(routes), 19)
# every app_old connections/recommendations path must still exist
import json
old = json.load(open("old.json"))
old_paths = sorted({f'{e["method"]} {e["full"]}' for e in old["endpoints"]
                    if e["file"].split("/")[2] == "connections"})
check("routes match app_old exactly", routes, old_paths)

# --- dead scaffolding removed (app_old had no engine.py/scoring.py either) ---
for f in ["recommendation/engine.py", "recommendation/scoring.py",
          "recommendation/session_taste", "domain/interfaces/recommender.py"]:
    check(f"removed {f}", os.path.exists(f"../app/modules/connections/{f}"), False)
check("vectors.py kept (real logic)",
      os.path.exists("../app/modules/connections/recommendation/vectors.py"), True)

# --- the N+1 fix --------------------------------------------------------------
# the query now lives in the repository; the eager load must have moved with it
src = open("../app/modules/connections/data/repository.py").read()
fn = src[src.index("def search_profiles"):]
check("search_profiles eager-loads Profile.business",
      "joinedload(Profile.business)" in fn[:2500], True)
# and the module must be SQL-free above the data layer
check("no db.query in connections application layer",
      count("grep -rl 'db\\.query' ../app/modules/connections/application | wc -l"), 0)
check("no db.query in connections presentation layer",
      count("grep -rl 'db\\.query' ../app/modules/connections/presentation | wc -l"), 0)
from app.modules.connections.data.repository import ConnectionsRepository
from app.modules.connections.domain.interfaces.repository import IConnectionsRepository
check("ConnectionsRepository implements the interface",
      issubclass(ConnectionsRepository, IConnectionsRepository), True)
check("no unimplemented abstract methods", sorted(ConnectionsRepository.__abstractmethods__), [])
# the four byte-identical _fmt_profile copies are now one
check("fmt_profile defined exactly once",
      count("grep -rl 'def fmt_profile' ../app/modules/connections | wc -l"), 1)

if fails:
    print("FAIL\n" + "\n".join(fails)); sys.exit(1)
print("PASS - connections (19 live routes, amplify ported + boost maths, dead scaffolding gone, N+1 fixed)")
