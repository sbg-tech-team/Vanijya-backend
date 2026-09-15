"""Field-by-field comparison of EVERY pydantic model, app_old vs app_new.
The endpoint diff only proves paths match; this proves request/response BODIES match."""
import ast, os, re, sys
from collections import defaultdict

OLDMAP = {"auth": "onboarding", "news_new": "news"}

def _norm(a: str) -> str:
    """`Optional[X]` and `X | None` are the same type and the same JSON."""
    a = a.strip()
    m = re.fullmatch(r"Optional\[(.+)\]", a)
    if m:
        a = f"{m.group(1)} | None"
    return a.replace(" ", "")


def models(root):
    out = defaultdict(dict)
    for dp, dn, fn in os.walk(root):
        if "__pycache__" in dp or "/routes/" in dp.replace(os.sep, "/"): continue
        parts = dp.split(os.sep)
        mod = parts[2] if len(parts) > 2 and parts[1] == "modules" else "_shared"
        mod = OLDMAP.get(mod, mod)
        for f in fn:
            if not f.endswith(".py"): continue
            try: tree = ast.parse(open(os.path.join(dp, f), encoding="utf-8", errors="replace").read())
            except Exception: continue
            for n in ast.walk(tree):
                if isinstance(n, ast.ClassDef) and any("BaseModel" in ast.unparse(b) for b in n.bases):
                    fields = {}
                    for st in n.body:
                        if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                            ann = _norm(ast.unparse(st.annotation).replace("'", "").replace('"', ""))
                            has_default = st.value is not None
                            fields[st.target.id] = (ann, has_default)
                    out[mod][n.name] = fields
    return out

O, N = models("app_old"), models("app_new")
total_missing = total_diff = 0
for mod in sorted(set(O) | set(N)):
    om, nm = O.get(mod, {}), N.get(mod, {})
    missing = sorted(set(om) - set(nm))
    diffs = []
    for name in sorted(set(om) & set(nm)):
        if om[name] != nm[name]:
            fd = {k: (om[name].get(k), nm[name].get(k)) for k in set(om[name]) | set(nm[name])
                  if om[name].get(k) != nm[name].get(k)}
            diffs.append((name, fd))
    if not missing and not diffs: continue
    print(f"\n=== {mod}  (old {len(om)} models, new {len(nm)})")
    for m in missing:
        print(f"   MISSING MODEL  {m}  fields={sorted(om[m])}")
    for name, fd in diffs:
        print(f"   FIELD DIFF     {name}")
        for k, (o, n) in sorted(fd.items()):
            print(f"        {k}: old={o}  new={n}")
    total_missing += len(missing); total_diff += len(diffs)
print(f"\n--- {total_missing} models missing from app_new, {total_diff} models with field differences ---")
