"""Statically resolve every intra-app import. Exit 1 if any is unresolvable.
Skips name-checks on modules that re-export via `import *` (can't resolve statically)."""
import ast, os, sys
ROOT = sys.argv[1] if len(sys.argv) > 1 else "app_new"

def path_for(mod):
    base = os.path.join(ROOT, *mod.split(".")[1:])
    if os.path.isfile(base + ".py"): return base + ".py"
    if os.path.isdir(base): return os.path.join(base, "__init__.py")
    return None

_cache = {}
def info(fp):
    if fp in _cache: return _cache[fp]
    names, star = set(), False
    try: tree = ast.parse(open(fp, encoding="utf-8", errors="replace").read())
    except Exception: return _cache.setdefault(fp, (set(), True))
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): names.add(n.name)
        elif isinstance(n, ast.Assign):
            names |= {t.id for t in n.targets if isinstance(t, ast.Name)}
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name): names.add(n.target.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                if a.name == "*": star = True
                else: names.add(a.asname or a.name.split(".")[0])
    return _cache.setdefault(fp, (names, star))

bad = []
for dp, dn, fn in os.walk(ROOT):
    if "__pycache__" in dp: continue
    for f in fn:
        if not f.endswith(".py"): continue
        fp = os.path.join(dp, f)
        try: tree = ast.parse(open(fp, encoding="utf-8", errors="replace").read())
        except Exception as e: bad.append(f"{fp}:0  SYNTAX: {e}"); continue
        for n in ast.walk(tree):
            if not isinstance(n, ast.ImportFrom) or not n.module or not n.module.startswith("app."): continue
            tgt = path_for(n.module)
            if tgt is None or not os.path.exists(tgt):
                bad.append(f"{fp}:{n.lineno}  NO MODULE: {n.module}"); continue
            names, star = info(tgt)
            if star: continue
            for a in n.names:
                if a.name == "*" or path_for(f"{n.module}.{a.name}"): continue
                if a.name not in names:
                    bad.append(f"{fp}:{n.lineno}  {n.module} has no '{a.name}'")
for b in sorted(bad): print(b)
print(f"\n--- {len(bad)} unresolved in {ROOT} ---")
sys.exit(1 if bad else 0)
