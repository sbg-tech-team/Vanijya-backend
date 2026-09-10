import json, sys, re
old = json.load(open("_migration/old.json")); new = json.load(open("_migration/new.json"))

def mod(fp):
    p = fp.split("/")
    return p[2] if len(p) > 2 and p[1] == "modules" else p[1]

# normalise: {method} {path}, path params renamed to {} so names don't matter
def key(e): return e["method"] + " " + re.sub(r"\{[^}]+\}", "{}", e["full"])

O = {}; N = {}
for e in old["endpoints"]: O.setdefault(key(e), []).append(e)
for e in new["endpoints"]: N.setdefault(key(e), []).append(e)

print("="*100); print("MODULE ENDPOINT COUNTS"); print("="*100)
from collections import Counter
co = Counter(mod(e["file"]) for e in old["endpoints"])
cn = Counter(mod(e["file"]) for e in new["endpoints"])
for m in sorted(set(co) | set(cn)):
    print(f"  {m:<28} old:{co.get(m,0):>3}   new:{cn.get(m,0):>3}")

missing = sorted(set(O) - set(N))
added   = sorted(set(N) - set(O))
print(); print("="*100); print(f"IN OLD, NOT IN NEW  ({len(missing)})"); print("="*100)
for k in missing:
    for e in O[k]: print(f"  {k:<52} {mod(e['file']):<14} {e['file'].split('/',1)[1]}:{e['line']}")
print(); print("="*100); print(f"IN NEW, NOT IN OLD  ({len(added)})"); print("="*100)
for k in added:
    for e in N[k]: print(f"  {k:<52} {mod(e['file']):<14} {e['file'].split('/',1)[1]}:{e['line']}")
