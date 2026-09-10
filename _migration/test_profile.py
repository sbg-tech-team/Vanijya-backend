"""Profile contract test — 11 routes, response model fields, error mapping.
    python3.12 _migration/test_profile.py
"""
import _boot  # noqa: F401
import ast, sys

from app.modules.profile.presentation.router import router

fails = []
def check(label, got, want):
    if got != want: fails.append(f"  {label}\n     got:  {got!r}\n     want: {want!r}")

# --- routes must match app_old exactly ---------------------------------------
check("route set", sorted(f"{sorted(r.methods)[0]} {r.path}" for r in router.routes),
      ["DELETE /profile/", "DELETE /profile/user", "GET /profile/avatar-upload-url",
       "GET /profile/by-user/{user_id}", "GET /profile/me", "GET /profile/{profile_id}",
       "PATCH /profile/", "PATCH /profile/avatar", "PATCH /profile/user/fcm-token",
       "POST /profile/", "POST /profile/user"])

# --- every response/request model field must match app_old byte-for-byte -----
def models(paths):
    out = {}
    for p in paths:
        for n in ast.walk(ast.parse(open(p).read())):
            if isinstance(n, ast.ClassDef) and any("BaseModel" in ast.unparse(b) for b in n.bases):
                out[n.name] = {st.target.id: ast.unparse(st.annotation)
                               for st in n.body
                               if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name)}
    return out

OLD = models(["../app_v1_backup/modules/profile/schemas.py"])
NEW = models(["../app/modules/profile/presentation/schemas.py",
              "../app/modules/profile/application/schemas.py"])
check("model set", sorted(NEW), sorted(OLD))
for name in sorted(OLD):
    if name not in NEW: continue
    # List['X'] vs List[X] is the same wire shape; normalise quotes only
    norm = lambda d: {k: v.replace("'", "") for k, v in d.items()}
    check(f"model {name} fields", norm(NEW[name]), norm(OLD[name]))

# --- the field that was renamed and had to be put back -----------------------
check("ProfilePublicResponse keeps app_old's posts_count key",
      "posts_count" in NEW["ProfilePublicResponse"], True)
check("page_posts_count is gone",
      "page_posts_count" in NEW["ProfilePublicResponse"], False)

# --- ok() messages and error mapping must be unchanged -----------------------
import re
def msgs(p):  return re.findall(r'ok\([^,]+,\s*"([^"]*)"', open(p).read())
def errs(p):  return sorted(re.findall(r'status_code=(\d+), detail=', open(p).read()))
check("ok() messages", msgs("../app/modules/profile/presentation/router.py"),
      msgs("../app_v1_backup/modules/profile/router.py"))
check("error status codes", errs("../app/modules/profile/presentation/router.py"),
      errs("../app_v1_backup/modules/profile/router.py"))

# --- layering ------------------------------------------------------------------
import subprocess
def count(cmd): return int(subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip() or 0)
check("no SQL in profile application layer",
      count("grep -rl 'db\\.query' ../app/modules/profile/application | wc -l"), 0)
check("no SQL in profile presentation layer",
      count("grep -rl 'db\\.query' ../app/modules/profile/presentation | wc -l"), 0)
check("router no longer builds the repo inline",
      count("grep -cE '(^|[^I])ProfileRepository' ../app/modules/profile/presentation/router.py"), 0)

if fails:
    print("FAIL\n" + "\n".join(fails)); sys.exit(1)
print("PASS - profile contract matches app_old (11 routes, all 10 models field-exact, messages, error codes, layering)")
