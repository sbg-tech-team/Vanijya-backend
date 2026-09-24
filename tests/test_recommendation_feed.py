"""The feed must survive an empty candidate pool.

`_rerank` returned three values on its normal path and two on its empty-pool
early return, so any profile whose pool came back empty — a brand-new account,
or one that has already seen everything — crashed on the caller's unpack. The
router caught ValueError and reported it as `404 "not enough values to unpack
(expected 3, got 2)"`, which hid it from Sentry and made it look like a
missing-profile error.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.modules.post.recommendation.constants import VECTOR_DIM  # noqa: E402
from app.modules.post.recommendation.engine import _rerank  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  PASS  {label}")
    else:
        failures.append(label)
        print(f"  FAIL  {label}\n        got:  {got!r}\n        want: {want!r}")


# The crash: an empty pool must still unpack into three values, exactly as the
# caller does — `scored, posts, authors = _rerank(...)`.
result = _rerank(
    repo=None, candidates=[], cat_weights={}, commodity_weights={},
    author_weights={}, city_weights={}, state_weights={}, followed_user_ids=set(),
)
check("empty pool returns 3 values", len(result), 3)

scored, posts, authors = result  # this line is the original bug
check("scored is empty", scored, [])
check("posts is empty", posts, {})
check("authors is empty", authors, {})

# A missing profile must raise the dedicated type, not a bare ValueError —
# otherwise the router's 404 handler swallows unrelated internal errors again.
from app.modules.post.domain.exceptions import ProfileNotFoundError  # noqa: E402
from app.modules.post.recommendation import engine  # noqa: E402


class _NoProfileRepo:
    def get_profile_with_commodities(self, profile_id):
        return None


try:
    engine.get_recommended_posts(_NoProfileRepo(), 1)
    check("missing profile raises", "no exception", "ProfileNotFoundError")
except ProfileNotFoundError:
    check("missing profile raises ProfileNotFoundError", True, True)
except Exception as exc:
    check("missing profile raises ProfileNotFoundError", type(exc).__name__, "ProfileNotFoundError")

check("ProfileNotFoundError is not a ValueError",
      issubclass(ProfileNotFoundError, ValueError), False)

# ── the empty-pool fallback ─────────────────────────────────────────────────
# Every ranked source needs an active embedding, and embeddings expire. When
# they all come back empty the feed used to be blank even though thousands of
# posts existed. Now it drops to recency.

class _FallbackRepo:
    """Every ranked source empty, posts still in the table."""

    def __init__(self, n_latest=30):
        self.latest_called_with = None
        self._n = n_latest

    def get_profile_with_commodities(self, profile_id):
        class _B: latitude, longitude = 19.0, 72.8
        class _P:
            id, users_id, role_id = 121, "u", 1
            commodities, quantity_min, quantity_max, business = [], 1, 10, _B()
        return _P()

    def user_post_feed_vector(self, users_id):  return None
    def all_followed_user_ids(self, users_id):  return set()
    def seen_post_ids_since(self, *a, **k):     return []
    def ann_post_candidates(self, *a, **k):     return []
    def popular_post_candidates(self, *a, **k): return []
    def fresh_post_candidates(self, *a, **k):   return []
    def get_category_taste_weights(self, *a, **k): return {}
    def global_taste_rows(self, *a, **k):        return []
    def global_taste_rows_bulk(self, *a, **k):   return []
    def all_commodities(self):                   return []

    @property
    def taste(self):
        class _T:
            def taste_rows(self, *a, **k):        return []
            def global_taste_rows(self, *a, **k): return []
        return _T()

    def latest_post_candidates(self, limit, exclude_ids):
        self.latest_called_with = (limit, set(exclude_ids))
        return [{"post_id": i, "category_id": 1, "target_roles": None}
                for i in range(1, self._n + 1)]

    def get_posts_by_ids(self, ids):        return []
    def get_authors_with_business(self, i): return []


repo = _FallbackRepo()
out = engine.get_recommended_posts(repo, 121, limit=20, rc=None)
check("fallback queried latest posts", repo.latest_called_with is not None, True)
# get_posts_by_ids returns nothing here, so _rerank drops them — what this
# proves is that the fallback RAN, which is the bug that mattered.
check("fallback asked for more than the page size",
      repo.latest_called_with[0] > 20, True)

# ...and that it does NOT run when a ranked source produced something, or
# every feed would be diluted with stale posts.
class _HasCandidates(_FallbackRepo):
    # signature order matters: repo.ann_post_candidates(vec_str, partition, ...)
    def ann_post_candidates(self, vec_str, partition, *a, **k):
        return [{"post_id": 99, "category": "market_update",
                 "vector": [0.1] * VECTOR_DIM}] if partition == "hot" else []

repo2 = _HasCandidates()
engine.get_recommended_posts(repo2, 121, limit=20, rc=None)
check("fallback skipped when ranked sources produced candidates",
      repo2.latest_called_with, None)

if failures:
    sys.exit(f"\nFAIL - {len(failures)} check(s) failed: {failures}")
print("\nPASS - recommendation feed survives an empty pool, 404 stays narrow")
