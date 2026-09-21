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

if failures:
    sys.exit(f"\nFAIL - {len(failures)} check(s) failed: {failures}")
print("\nPASS - recommendation feed survives an empty pool, 404 stays narrow")
