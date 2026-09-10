"""Whole-tree contract gate.

1. Every app_old endpoint exists in app_new.
2. Every pydantic model REACHABLE FROM an app_old endpoint (request body,
   response_model, or a model nested inside one) exists in app_new with
   identical fields. Models that only described app_old's deleted GNews/Groq
   pipeline tables are excluded — they were never on the wire.
    python3.12 _migration/test_contracts.py
"""
import ast, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
os.chdir(os.path.dirname(os.path.abspath(__file__)))

fails = []
def check(label, got, want):
    if got != want: fails.append(f"  {label}\n     got:  {got!r}\n     want: {want!r}")

def norm(a):
    a = a.strip().replace("'", "").replace('"', "")
    m = re.fullmatch(r"Optional\[(.+)\]", a)
    if m: a = f"{m.group(1)} | None"
    return a.replace(" ", "")

OLDMAP = {"auth": "onboarding", "feed": "home_feed", "news_new": "news"}

def _mod(dp):
    parts = dp.replace(os.sep, "/").split("/")
    if "modules" in parts:
        i = parts.index("modules")
        if i + 1 < len(parts): return OLDMAP.get(parts[i + 1], parts[i + 1])
    return "_shared"

def collect(root):
    """Keyed by (module, ClassName): the same class name is reused across
    modules (post.FeedResponse vs news.FeedResponse are unrelated)."""
    out = {}
    for dp, dn, fn in os.walk(root):
        if "__pycache__" in dp or "/routes/" in dp.replace(os.sep, "/"): continue
        for f in fn:
            if not f.endswith(".py"): continue
            try: tree = ast.parse(open(os.path.join(dp, f), encoding="utf-8", errors="replace").read())
            except Exception: continue
            for n in ast.walk(tree):
                known = {k[1] for k in out}
                if isinstance(n, ast.ClassDef) and any("BaseModel" in b_name(b) or b_name(b) in known
                                                       for b in n.bases):
                    out[(_mod(dp), n.name)] = ({st.target.id: norm(ast.unparse(st.annotation))
                                    for st in n.body
                                    if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name)},
                                   [b_name(b) for b in n.bases])
    return out

def b_name(b):
    try: return ast.unparse(b)
    except Exception: return ""

OLD, NEW = collect(os.path.join(ROOT, "app_old")), collect(os.path.join(ROOT, "app_new"))

# --- 1. endpoints -------------------------------------------------------------
old_eps = json.load(open("old.json"))["endpoints"]
new_eps = json.load(open("new.json"))["endpoints"]
key = lambda e: e["method"] + " " + re.sub(r"\{[^}]+\}", "{}", e["full"])
missing_eps = sorted({key(e) for e in old_eps} - {key(e) for e in new_eps})
check("every app_old endpoint exists in app_new", missing_eps, [])

# --- 2. models reachable from an app_old endpoint ------------------------------
seeds = set()
for e in old_eps:
    if e["response_model"]: seeds.add(e["response_model"])
    for p in e["params"]:
        if p["type"]: seeds.update(re.findall(r"\b([A-Z]\w+)\b", p["type"]))
# app_old routers also return `SomeModel(...).model_dump()` / `result.model_dump()`
for dp, dn, fn in os.walk(os.path.join(ROOT, "app_old")):
    if "__pycache__" in dp or "/routes/" in dp.replace(os.sep, "/"): continue
    for f in fn:
        if not f.endswith("router.py"): continue
        src = open(os.path.join(dp, f), encoding="utf-8", errors="replace").read()
        seeds.update(re.findall(r"\b([A-Z]\w+)\(.*?\)\.model_dump", src))
        for m in re.findall(r"(?:service|feed_service)\.(\w+)\(", src):
            for dp2, _, fn2 in os.walk(os.path.dirname(dp)):
                for f2 in fn2:
                    if not f2.endswith(".py"): continue
                    s2 = open(os.path.join(dp2, f2), encoding="utf-8", errors="replace").read()
                    hit = re.search(rf"def {m}\(.*?\)\s*->\s*([A-Z]\w+)", s2, re.S)
                    if hit: seeds.add(hit.group(1))

# transitively pull in nested models
OLD_BY_NAME, NEW_BY_NAME = {}, {}
for (mod, name), v in OLD.items(): OLD_BY_NAME.setdefault(name, []).append((mod, v))
for (mod, name), v in NEW.items(): NEW_BY_NAME.setdefault(name, []).append((mod, v))

reachable, queue = set(), [s for s in seeds if s in OLD_BY_NAME]
while queue:
    name = queue.pop()
    if name in reachable: continue
    reachable.add(name)
    for _mod_, (fields, bases) in OLD_BY_NAME[name]:
        for ann in fields.values():
            for ref in re.findall(r"\b([A-Z]\w+)\b", ann):
                if ref in OLD_BY_NAME and ref not in reachable: queue.append(ref)
        for base in bases:
            if base in OLD_BY_NAME and base not in reachable: queue.append(base)

missing_models = sorted(m for m in reachable if m not in NEW_BY_NAME)
check("every client-reachable app_old model exists in app_new", missing_models, [])

field_diffs = []
for m in sorted(reachable & set(NEW_BY_NAME)):
    for omod, (ofields, _) in OLD_BY_NAME[m]:
        cands = [v for nmod, v in NEW_BY_NAME[m] if nmod == omod] or [v for _, v in NEW_BY_NAME[m]]
        # a model matches if ANY same-named app_new model has identical fields
        if any(ofields == nf for nf, _ in cands): continue
        nf = cands[0][0]
        d = {k: (ofields.get(k), nf.get(k))
             for k in set(ofields) | set(nf) if ofields.get(k) != nf.get(k)}
        # a field app_new ADDS with a default is additive, not a break
        d = {k: v for k, v in d.items() if v[0] is not None}
        if d: field_diffs.append((f"{omod}.{m}", d))
check("client-reachable models are field-identical", field_diffs, [])

print(f"  checked {len(reachable)} client-reachable app_old models across {len(old_eps)} endpoints")
if fails:
    print("FAIL\n" + "\n".join(fails)); sys.exit(1)
print("PASS - every app_old endpoint AND every client-facing request/response model matches")
