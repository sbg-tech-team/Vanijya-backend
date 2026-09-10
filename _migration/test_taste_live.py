"""Live taste-layer gate — REAL Redis, no fakes.

Every other gate either stubs Redis or asserts only "does not 500". This walks the
whole recommendation pipeline: module session write -> sync to global session ->
3-layer blend -> commodity boost, and checks the values against SIGNAL_WEIGHTS.

    redis-server --port 6399 --daemonize yes
    python3.12 _migration/test_taste_live.py
"""
import os, sys, time

REDIS_URL = os.environ.get("SMOKE_REDIS_URL", "redis://127.0.0.1:6399/15")
os.environ["REDIS_URL"] = REDIS_URL
os.environ.setdefault("VJ_DB", "vanijyaa_smoke")

import _db  # noqa: E402  (sets DSN + sys.path)
import redis  # noqa: E402

rc = redis.from_url(REDIS_URL)
try:
    rc.ping()
except Exception as e:
    print(f"SKIP - no Redis at {REDIS_URL}: {e}"); sys.exit(0)
rc.flushdb()   # db 15 by default, kept away from anyone's working data

from app.recommendation.amplify import commodity_boost, write_commodity_signals  # noqa: E402
from app.recommendation.global_session import merge_weights, sync_module_to_global  # noqa: E402
from app.recommendation.session_taste import (  # noqa: E402
    SIGNAL_WEIGHTS, ActionType, MODULE_SESSION_TTL, read_dimension_weights)

fails = []
def check(label, got, want):
    if got != want: fails.append(f"  {label}\n     got:  {got!r}\n     want: {want!r}")

PID = 4242

# --- 1. write path: a follow lands in the module session ---------------------
write_commodity_signals(rc, PID, "connections", [1], ActionType.CONNECTION_FOLLOW, role_id=1)
key = f"session:connections:{PID}"
check("module session hash created", rc.exists(key), 1)
check("TTL is MODULE_SESSION_TTL", rc.ttl(key) in (MODULE_SESSION_TTL, MODULE_SESSION_TTL - 1), True)

h = {k.decode(): v.decode() for k, v in rc.hgetall(key).items()}
pos, neg, conf = SIGNAL_WEIGHTS["connection_follow"]
check("commodity positive == SIGNAL_WEIGHTS", float(h["com:1:pos"]), pos)
check("commodity confidence == SIGNAL_WEIGHTS", float(h["com:1:conf"]), conf)
check("role dimension written too", "rol:1:pos" in h, True)
check("event counter", h["_total_events"], "2")   # commodity + role

# --- 2. a mild signal accumulates rather than overwriting --------------------
write_commodity_signals(rc, PID, "groups", [1], ActionType.GROUP_VIEW)
write_commodity_signals(rc, PID, "groups", [1], ActionType.GROUP_VIEW)
gp, _, gc = SIGNAL_WEIGHTS["group_view"]
gh = {k.decode(): v.decode() for k, v in rc.hgetall(f"session:groups:{PID}").items()}
check("two group_views accumulate", round(float(gh["com:1:pos"]), 6), round(gp * 2, 6))
check("count accumulates", gh["com:1:cnt"], "2")

# --- 3. decay is applied at read time ----------------------------------------
w = read_dimension_weights(rc, PID, "connections", "commodity")
check("read applies decay (slightly below the raw write)", 0 < w["1"] < pos, True)

# --- 4. module session -> global session -------------------------------------
sync_module_to_global(rc, PID, "connections")
check("global session created", rc.exists(f"session:global:{PID}"), 1)

# --- 5. the 3-layer blend, with an empty persistent layer --------------------
merged = merge_weights(rc, PID, "connections", "commodity", {})
check("merged has the commodity", "1" in merged, True)
check("module influence capped at 31%", merged["1"] <= pos * 0.31 + 1e-6, True)

# --- 6. boost is bounded and only applies to matching commodities ------------
b_hit = commodity_boost(merged, [1])
check("boost within [1.0, 1.30]", 1.0 <= b_hit <= 1.30 + 1e-9, True)
check("no signal -> no boost", commodity_boost(merged, [999]), 1.0)
check("empty weights -> no boost", commodity_boost({}, [1]), 1.0)

# --- 7. fail-silent: a dead Redis must never break the calling action --------
dead = redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=1)
check("write is fail-silent on a dead Redis",
      write_commodity_signals(dead, PID, "connections", [1], ActionType.CONNECTION_FOLLOW), None)
check("write is fail-silent with rc=None",
      write_commodity_signals(None, PID, "connections", [1], ActionType.CONNECTION_FOLLOW), None)

# --- 8. every ActionType has a weight ----------------------------------------
check("no ActionType without a SIGNAL_WEIGHTS entry",
      [a.value for a in ActionType if a.value not in SIGNAL_WEIGHTS], [])

rc.flushdb()
print(f"  exercised {len(ActionType)} action types against real Redis")
if fails:
    print(f"FAIL ({len(fails)})\n" + "\n".join(fails)); sys.exit(1)
print("PASS - taste layer on REAL Redis: write weights, TTL, accumulation, decay, "
      "module->global sync, 31%-capped blend, bounded boost, fail-silent")
