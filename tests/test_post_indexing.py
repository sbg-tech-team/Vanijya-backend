"""Post indexing must actually run.

Every index_post / remove_post_index call site sits inside a broad
`except Exception`, so a signature mismatch here fails silently and no post ever
reaches the recommendation feed. That is exactly what happened: all three call
sites passed `repo=` while the function took `db`, so every call raised
TypeError and was swallowed.

    PYTHONPATH=. .venv/bin/python tests/test_post_indexing.py
"""
import inspect
import sys

from app.modules.post.recommendation import service as rec_service

fails = []


def check(label, got, want):
    if got != want:
        fails.append(f"  {label}\n     got:  {got!r}\n     want: {want!r}")


# ── 1. Every call site can actually bind ─────────────────────────────────────
INDEX_KWARGS = dict(
    repo=None, post_id=1, commodity_id=1, target_role_ids=None,
    lat=0.0, lon=0.0, category_id=1, commodity_quantity=1.0,
)
try:
    inspect.signature(rec_service.index_post).bind(**INDEX_KWARGS)
    check("index_post accepts the kwargs its callers pass", True, True)
except TypeError as e:
    check("index_post accepts the kwargs its callers pass", str(e), "binds")

try:
    inspect.signature(rec_service.remove_post_index).bind(repo=None, post_id=1)
    check("remove_post_index accepts repo=", True, True)
except TypeError as e:
    check("remove_post_index accepts repo=", str(e), "binds")


# ── 2. It writes through the repository, and does not commit ─────────────────
class FakeRepo:
    def __init__(self):
        self.upserts = []
        self.deactivated = []
        self.commits = 0

    def upsert_post_embedding(self, post_id, vector, category, commodity_idx, expires_at, now):
        self.upserts.append((post_id, len(vector), category, commodity_idx))

    def deactivate_post_embedding(self, post_id):
        self.deactivated.append(post_id)

    def commit(self):
        self.commits += 1


repo = FakeRepo()
rec_service.index_post(
    repo=repo, post_id=42, commodity_id=1, target_role_ids=[1],
    lat=19.07, lon=72.87, category_id=1, commodity_quantity=100.0,
)
check("index_post wrote one embedding", len(repo.upserts), 1)
check("index_post wrote it for the right post", repo.upserts[0][0], 42)
check("the vector is non-empty", repo.upserts[0][1] > 0, True)
check("index_post does not commit (caller owns the transaction)", repo.commits, 0)

rec_service.remove_post_index(repo, 42)
check("remove_post_index deactivated the embedding", repo.deactivated, [42])
check("remove_post_index does not commit", repo.commits, 0)


# ── 3. Both repositories that index posts implement the contract ─────────────
from app.modules.post.data.repository import PostRepository
from app.modules.groups.data.repository import GroupsRepository

for cls in (PostRepository, GroupsRepository):
    for m in ("upsert_post_embedding", "deactivate_post_embedding"):
        check(f"{cls.__name__}.{m} exists", hasattr(cls, m), True)
    check(f"{cls.__name__} has no unimplemented abstract methods",
          sorted(cls.__abstractmethods__), [])


if fails:
    print(f"FAIL ({len(fails)})\n" + "\n".join(fails))
    sys.exit(1)
print(f"PASS - post indexing: call sites bind, writes go through the repository, "
      f"no inner commit, both repositories implement the contract")
