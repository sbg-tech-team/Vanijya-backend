"""Groups contract test — restored /view endpoint and the three amplify hooks.
    python3.12 _migration/test_groups.py
"""
import _boot  # noqa: F401
import inspect, json, subprocess, sys

from app.modules.groups.presentation.router import router
from app.modules.groups.presentation.schemas import GroupViewSignal
from app.modules.groups.application.use_cases.service import record_group_view
from app.modules.groups.application.use_cases.manage_members import join_group
from app.modules.groups.application.use_cases.get_group_suggestions import get_group_suggestions
from app.recommendation.session_taste import ActionType

fails = []
def check(label, got, want):
    if got != want: fails.append(f"  {label}\n     got:  {got!r}\n     want: {want!r}")

# --- every app_old groups route present --------------------------------------
old = json.load(open("old.json"))
old_paths = sorted({f'{e["method"]} {e["full"]}' for e in old["endpoints"]
                    if e["file"].split("/")[2] == "groups"})
new_paths = sorted({f"{sorted(r.methods)[0]} {r.path}" for r in router.routes})
check("routes match app_old exactly", new_paths, old_paths)

# --- POST /view was deleted in app_new ---------------------------------------
check("POST /api/v1/groups/view restored", "POST /api/v1/groups/view" in new_paths, True)
view = [r for r in router.routes if r.path == "/api/v1/groups/view"][0]
check("view returns 204", view.status_code, 204)
# it must be matched before /{group_id}, or a UUID path would swallow it
paths = [r.path for r in router.routes]
check("/view declared before /{group_id} routes",
      paths.index("/api/v1/groups/view") < min(i for i, p in enumerate(paths) if "{group_id}" in p), True)

# --- schema restored -----------------------------------------------------------
check("GroupViewSignal fields", sorted(GroupViewSignal.model_fields), ["commodity_ids", "group_id"])
check("commodity_ids defaults to []", GroupViewSignal(group_id="11111111-1111-1111-1111-111111111111").commodity_ids, [])

# --- the three amplify hooks app_new had dropped ------------------------------
check("record_group_view exported", callable(record_group_view), True)
check("record_group_view is fail-silent without redis",
      record_group_view(None, viewer_profile_id=1, commodity_ids=[1]), None)
check("join_group accepts rc + actor_profile_id",
      {"rc", "actor_profile_id"} <= set(inspect.signature(join_group).parameters), True)
check("get_group_suggestions accepts rc",
      "rc" in inspect.signature(get_group_suggestions).parameters, True)

src = open("../app/modules/groups/application/use_cases/get_group_suggestions.py").read()
check("suggestions apply commodity_boost to semantic score",
      "compute_final_score(sim * boost, act)" in src, True)
mm = open("../app/modules/groups/application/use_cases/manage_members.py").read()
check("GROUP_JOIN fired on both join paths",
      len([l for l in mm.split("\n") if l.strip() == "_record()"]), 2)
check("GROUP_JOIN action used", "ActionType.GROUP_JOIN" in mm, True)
check("ActionType.GROUP_JOIN exists", ActionType.GROUP_JOIN.value, "group_join")

# --- the boot blocker that also blocked chat ----------------------------------
from app.modules.groups.application.use_cases.service import ALLOWED_MEDIA_TYPES
check("ALLOWED_MEDIA_TYPES importable from service", bool(ALLOWED_MEDIA_TYPES), True)

if fails:
    print("FAIL\n" + "\n".join(fails)); sys.exit(1)
print("PASS - groups (routes match app_old, /view restored, all 3 amplify hooks back)")
