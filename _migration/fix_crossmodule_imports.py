"""Rewrite `from app.modules.X import name` -> the concrete defining module.

Importing through a package __init__ requires an *attribute* of a possibly
half-initialised package; importing the submodule directly does not. That is
what breaks the profile <-> onboarding <-> post cycles.
Name->module map is taken from each package's own __init__.py, so this changes
resolution path only, never which object is imported.
"""
import ast, os, sys

MAP = {
    "profile": {n: "app.modules.profile.data.models" for n in
                ["User","Profile","Role","Commodity","Interest","Profile_Commodity","Business","UserEmbedding"]},
    "post": {"Post": "app.modules.post.data.models",
             "_batch_feed_cards": "app.modules.post.application.service",
             "build_user_feed_vector": "app.modules.post.recommendation.vectors",
             "FeedPostCard": "app.modules.post.application.schemas"},
    "connections": {"UserConnection": "app.modules.connections.data.models",
                    "MessageRequest": "app.modules.connections.data.models",
                    "build_candidate_vector": "app.modules.connections.recommendation.vectors"},
    "onboarding": {n: "app.modules.onboarding.application.use_cases.service" for n in
                   ["create_session","refresh_session","revoke_session_by_jti",
                    "revoke_all_sessions","verify_firebase_token","issue_onboarding_token"]}
              | {"UserSession": "app.modules.onboarding.data.models"},
}
APPLY = "--apply" in sys.argv
changed = 0
for dp, dn, fn in os.walk("app_new/modules"):
    if "__pycache__" in dp: continue
    own = dp.split("/")[2] if len(dp.split("/")) > 2 else None
    for f in sorted(fn):
        if not f.endswith(".py"): continue
        fp = os.path.join(dp, f)
        lines = open(fp).read().split("\n")
        try: tree = ast.parse("\n".join(lines))
        except Exception: continue
        edits = {}
        for n in ast.walk(tree):
            if not isinstance(n, ast.ImportFrom) or not n.module: continue
            p = n.module.split(".")
            if not (len(p) == 3 and p[:2] == ["app","modules"] and p[2] != own and p[2] in MAP):
                continue
            groups = {}
            for a in n.names:
                tgt = MAP[p[2]].get(a.name)
                if tgt is None: groups = None; break
                groups.setdefault(tgt, []).append(a.name + (f" as {a.asname}" if a.asname else ""))
            if not groups: continue
            indent = lines[n.lineno-1][:len(lines[n.lineno-1]) - len(lines[n.lineno-1].lstrip())]
            new = [f"{indent}from {m} import {', '.join(sorted(ns))}" for m, ns in sorted(groups.items())]
            edits[(n.lineno, n.end_lineno)] = new
        if not edits: continue
        out, i = [], 0
        span = {s: (e, v) for (s, e), v in edits.items()}
        while i < len(lines):
            if i+1 in span:
                end, new = span[i+1]
                print(f"  {fp}:{i+1}")
                for o in lines[i:end]: print(f"      - {o.strip()}")
                for nl in new:        print(f"      + {nl.strip()}")
                out += new; i = end
            else:
                out.append(lines[i]); i += 1
        changed += 1
        if APPLY: open(fp, "w").write("\n".join(out))
print(f"\n--- {changed} files {'REWRITTEN' if APPLY else '(dry run)'} ---")
