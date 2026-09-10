"""Safety module contract test - locks the app_old JSON contract.

No database: the repository is faked at the interface boundary, which is only
possible because all SQL now lives behind ISafetyRepository.
    python3.12 _migration/test_safety.py
"""
import sys
from datetime import datetime, timezone
from uuid import UUID

import _boot  # noqa: F401  (path + SDK stubs)
from fastapi import FastAPI                                    # noqa: E402
from fastapi.testclient import TestClient                      # noqa: E402
from app.dependencies import get_current_user_id               # noqa: E402
from app.modules.safety.domain.entities import BlockedUser, Report   # noqa: E402
from app.modules.safety.domain.interfaces.repository import ISafetyRepository  # noqa: E402
from app.modules.safety.presentation.dependencies import get_safety_repo       # noqa: E402
from app.modules.safety.presentation.router import router      # noqa: E402

ME     = UUID("11111111-1111-1111-1111-111111111111")
TARGET = UUID("22222222-2222-2222-2222-222222222222")
NOW    = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


class FakeRepo(ISafetyRepository):
    def __init__(self):
        self.blocks, self.reports, self.next_id = set(), [], 1

    def block_exists(self, b, t):   return (b, t) in self.blocks
    def add_block(self, b, t):      self.blocks.add((b, t))
    def remove_block(self, b, t):
        if (b, t) not in self.blocks: return False
        self.blocks.discard((b, t)); return True
    def list_blocked(self, b, page, limit):
        rows = [BlockedUser(t, NOW, "Bob", "http://a/b.png") for (x, t) in sorted(self.blocks) if x == b]
        return rows[(page - 1) * limit:(page - 1) * limit + limit], len(rows)
    def either_blocked(self, a, b): return (a, b) in self.blocks or (b, a) in self.blocks
    def report_exists(self, r, tt, ti): return any(x for x in self.reports if (x.target_type, x.target_id) == (tt, ti))
    def add_report(self, r, tt, ti, reason, desc):
        rep = Report(self.next_id, tt, ti, reason, "pending", NOW)
        self.next_id += 1; self.reports.append(rep); return rep
    def list_reports(self, r, page, limit):
        return self.reports[(page - 1) * limit:(page - 1) * limit + limit], len(self.reports)


repo = FakeRepo()
app = FastAPI()
app.include_router(router)
app.dependency_overrides[get_current_user_id] = lambda: ME
app.dependency_overrides[get_safety_repo] = lambda: repo
c = TestClient(app)

fails = []
def check(label, got, want):
    if got != want:
        fails.append(f"  {label}\n     got:  {got}\n     want: {want}")

# --- URLs must be exactly app_old's -----------------------------------------
check("route set",
      sorted(f"{sorted(r.methods)[0]} {r.path}" for r in router.routes),
      sorted(["POST /safety/block/{target_id}", "DELETE /safety/block/{target_id}",
              "GET /safety/blocked", "GET /safety/block/status/{target_id}",
              "POST /safety/report", "GET /safety/reports"]))

# --- block ------------------------------------------------------------------
r = c.post(f"/safety/block/{TARGET}")
check("block 200", r.status_code, 200)
check("block body", r.json(), {"status": "blocked", "blocked_id": str(TARGET)})
check("block self -> 400", c.post(f"/safety/block/{ME}").status_code, 400)
check("re-block -> 409", c.post(f"/safety/block/{TARGET}").status_code, 409)

# --- list blocked: keys + pagination echo must match app_old ----------------
r = c.get("/safety/blocked", params={"page": 1, "limit": 20}).json()
check("blocked keys", sorted(r), ["blocked", "limit", "page", "total"])
check("blocked row keys", sorted(r["blocked"][0]), ["avatar_url", "blocked_at", "blocked_id", "name"])
check("blocked total/page/limit", (r["total"], r["page"], r["limit"]), (1, 1, 20))
check("limit>100 rejected", c.get("/safety/blocked", params={"limit": 101}).status_code, 422)

# --- status -----------------------------------------------------------------
check("status body", c.get(f"/safety/block/status/{TARGET}").json(),
      {"blocker_id": str(ME), "blocked_id": str(TARGET), "is_blocked": True})

# --- unblock ----------------------------------------------------------------
check("unblock body", c.delete(f"/safety/block/{TARGET}").json(),
      {"status": "unblocked", "blocked_id": str(TARGET)})
check("unblock twice -> 404", c.delete(f"/safety/block/{TARGET}").status_code, 404)

# --- report -----------------------------------------------------------------
body = {"target_type": "user", "target_id": str(TARGET), "reason": "spam", "description": "x"}
r = c.post("/safety/report", json=body)
check("report 200", r.status_code, 200)
check("report keys", sorted(r.json()), ["created_at", "id", "reason", "status", "target_id", "target_type"])
check("dup report -> 409", c.post("/safety/report", json=body).status_code, 409)
check("self report -> 400",
      c.post("/safety/report", json={**body, "target_id": str(ME)}).status_code, 400)
check("bad reason -> 422",
      c.post("/safety/report", json={**body, "reason": "nope"}).status_code, 422)
r = c.get("/safety/reports").json()
check("reports keys", sorted(r), ["limit", "page", "reports", "total"])

# --- auth is enforced, and NOT taken from the URL ---------------------------
noauth = FastAPI(); noauth.include_router(router)
noauth.dependency_overrides[get_safety_repo] = lambda: repo
check("no token -> 401", TestClient(noauth).post(f"/safety/block/{TARGET}").status_code, 401)

if fails:
    print("FAIL\n" + "\n".join(fails)); sys.exit(1)
print("PASS - safety contract matches app_old (6 routes, shapes, codes, auth)")
