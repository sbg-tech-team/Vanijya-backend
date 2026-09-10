"""Regenerate a repository ABC from its concrete class, so the two cannot drift.
    python3 _migration/gen_repo_interface.py <module> <IFaceName>
"""
import ast, re, sys

mod, iface = sys.argv[1], sys.argv[2]
cpath = f"app_new/modules/{mod}/data/repository.py"
ipath = f"app_new/modules/{mod}/domain/interfaces/repository.py"

cls = next(n for n in ast.parse(open(cpath).read()).body if isinstance(n, ast.ClassDef))
old_docs, header = {}, None
try:
    otree = ast.parse(open(ipath).read())
    for n in otree.body:
        if isinstance(n, ast.ClassDef):
            header = ast.get_docstring(n)
            for m in n.body:
                if isinstance(m, ast.FunctionDef):
                    d = ast.get_docstring(m)
                    if d: old_docs[m.name] = d
except Exception:
    pass

def sig(m):
    a = m.args
    parts, defaults = [], [None]*(len(a.args)-len(a.defaults)) + [ast.unparse(d) for d in a.defaults]
    for arg, d in zip(a.args, defaults):
        if arg.arg == "self": parts.append("self"); continue
        t = f": {ast.unparse(arg.annotation)}" if arg.annotation else ""
        parts.append(f"{arg.arg}{t}" + (f" = {d}" if d is not None else ""))
    if a.kwonlyargs: parts.append("*")
    for arg, d in zip(a.kwonlyargs, [ast.unparse(x) if x else None for x in a.kw_defaults]):
        t = f": {ast.unparse(arg.annotation)}" if arg.annotation else ""
        parts.append(f"{arg.arg}{t}" + (f" = {d}" if d is not None else ""))
    ret = ""
    if m.returns:
        r = ast.unparse(m.returns)
        # never let a SQLAlchemy type appear in the domain layer
        r = re.sub(r"\bSession\b", "Any", r)
        ret = f" -> {r}"
    return f"({', '.join(parts)}){ret}"

# The domain layer must not import SQLAlchemy/FastAPI/Pydantic. The concrete
# repository exposes a `session` escape hatch for cross-module helpers that still
# take a Session; in the interface that is typed `Any` so the leak stops here.
out = ["from __future__ import annotations", "", "from abc import ABC, abstractmethod",
       "from datetime import datetime", "from typing import Any, Optional",
       "from uuid import UUID", "", "",
       f"class {iface}(ABC):"]
out.append('    """' + (header or f"Every database access in the {mod} module goes through this interface.") + '"""')
out.append("")
n = 0
for m in cls.body:
    if not isinstance(m, ast.FunctionDef) or m.name.startswith("__"): continue
    is_prop = any(ast.unparse(d) == "property" for d in m.decorator_list)
    n += 1
    out.append("    @property" if is_prop else "    @abstractmethod")
    if is_prop: out.append("    @abstractmethod")
    out.append(f"    def {m.name}{sig(m)}:")
    d = old_docs.get(m.name) or ast.get_docstring(m)
    if d: out.append(f'        """{d.strip().splitlines()[0]}"""')
    out.append("        ...")
    out.append("")
open(ipath, "w").write("\n".join(out))
print(f"{iface}: {n} abstract members")
