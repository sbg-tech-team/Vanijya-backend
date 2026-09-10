"""Extract every HTTP endpoint contract from a FastAPI tree via AST.
No imports, no execution - pure static read of the actual source."""
import ast, os, sys, json

ROOT = sys.argv[1]
OUT  = sys.argv[2]

def src(n):
    try: return ast.unparse(n)
    except Exception: return "?"

class ModCollector(ast.NodeVisitor):
    """Collect pydantic models + router prefixes in one file."""
    def __init__(self):
        self.models = {}   # ClassName -> [ {name,type,required,default} ]
        self.routers = {}  # varname -> prefix

    def visit_ClassDef(self, node):
        bases = [src(b) for b in node.bases]
        if any("BaseModel" in b or "Schema" in b for b in bases):
            fields = []
            for st in node.body:
                if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                    d = src(st.value) if st.value is not None else None
                    req = d is None or d.startswith("Field(...")
                    fields.append({"name": st.target.id, "type": src(st.annotation),
                                   "required": req, "default": d})
            self.models[node.name] = {"fields": fields, "bases": bases}
        self.generic_visit(node)

    def visit_Assign(self, node):
        if (isinstance(node.value, ast.Call) and src(node.value.func).endswith("APIRouter")
                and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
            pfx, tags = "", []
            for kw in node.value.keywords:
                if kw.arg == "prefix": pfx = src(kw.value).strip("'\"")
                if kw.arg == "tags":   tags = src(kw.value)
            self.routers[node.targets[0].id] = pfx
        self.generic_visit(node)

def param_kind(default_src):
    if default_src is None: return "path_or_query"
    for k in ("Depends", "Body", "Query", "Path", "File", "Form", "Header"):
        if default_src.startswith(k + "("): return k
    return "default"

eps = []
allmodels = {}
# app_old/modules/connections/routes/ is dead code: it imports
# app.modules.connections.db, which does not exist, so app_old could not boot if
# anything registered it. Never included in either tree -> excluded from the
# contract surface. (app_new's copies, routes_*.py, have been deleted.)
DEAD = ("modules/connections/routes/",)

for dp, dn, fn in os.walk(ROOT):
    if "__pycache__" in dp: continue
    if any(d in dp.replace(os.sep, "/") + "/" for d in DEAD): continue
    for f in sorted(fn):
        if not f.endswith(".py"): continue
        fp = os.path.join(dp, f)
        try: tree = ast.parse(open(fp, encoding="utf-8", errors="replace").read())
        except Exception: continue
        c = ModCollector(); c.visit(tree)
        for k, v in c.models.items(): allmodels.setdefault(k, {"file": fp, **v})
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)): continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call): continue
                fsrc = src(dec.func)
                parts = fsrc.split(".")
                if len(parts) != 2 or parts[1] not in ("get","post","put","patch","delete"):
                    continue
                rvar, method = parts[0], parts[1].upper()
                path = src(dec.args[0]).strip("'\"") if dec.args else ""
                rm = next((src(k.value) for k in dec.keywords if k.arg == "response_model"), None)
                sc = next((src(k.value) for k in dec.keywords if k.arg == "status_code"), None)
                # params
                a = node.args
                defaults = [None]*(len(a.args)-len(a.defaults)) + [src(d) for d in a.defaults]
                params = []
                for arg, dflt in zip(a.args, defaults):
                    ann = src(arg.annotation) if arg.annotation else None
                    params.append({"name": arg.arg, "type": ann, "default": dflt,
                                   "kind": param_kind(dflt)})
                for arg, dflt in zip(a.kwonlyargs, [src(d) if d else None for d in a.kw_defaults]):
                    ann = src(arg.annotation) if arg.annotation else None
                    params.append({"name": arg.arg, "type": ann, "default": dflt,
                                   "kind": param_kind(dflt)})
                eps.append({
                    "file": fp, "line": node.lineno, "func": node.name,
                    "method": method, "router_var": rvar,
                    "router_prefix": c.routers.get(rvar, ""),
                    "path": path,
                    "full": (c.routers.get(rvar, "") + path) or "/",
                    "response_model": rm, "status_code": sc,
                    "params": params,
                })
json.dump({"endpoints": eps, "models": allmodels}, open(OUT, "w"), indent=1)
print(f"{ROOT}: {len(eps)} endpoints, {len(allmodels)} pydantic models -> {OUT}")
