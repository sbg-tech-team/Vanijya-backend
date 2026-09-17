"""
Taste Service — Phase 3

Manages the user_post_taste table: the row-per-dimension persistent taste store.

  update_taste()          – atomic upsert of a taste delta for one dimension row
  get_taste_weights()     – read decayed, confidence-blended scores for a dimension
  seed_taste_from_role()  – create initial category rows from role defaults
                            (called during onboarding; never overwrites learned data)

NOTE: This service is both the write path and the read path for every post
      feed — the recommendation feed and the following feed both rank on
      get_taste_weights(). The legacy user_taste_profiles table is retired.
"""
import math
from datetime import datetime, timezone


from app.modules.post.recommendation.session_taste.constants import (
    AUTHOR_AFFINITY_MAX,
    AUTHOR_AFFINITY_SATURATION,
    DEFAULT_TASTE,
    TASTE_BOOTSTRAP_EVENTS,
    TASTE_DECAY_LAMBDA,
)
from app.shared.utils.time_decay import decayed_score

_SCORE_FLOOR = 0.05          # no dimension can fall below this weight
_NEG_DISCOUNT = 0.6          # negative_score is discounted before subtracting


def update_taste(
    repo,
    profile_id: int,
    dimension_type: str,
    dimension_key: str,
    positive_delta: float,
    negative_delta: float = 0.0,
    event_count: int = 1,
) -> None:
    """
    Atomically upserts a single taste row.

    On insert:  sets scores to the given deltas, event_count to event_count.
    On conflict: adds deltas to existing scores, increments event_count.

    Does NOT commit — caller is responsible for the commit so that taste
    writes and the triggering interaction (like / dwell) commit atomically.
    """
    repo.upsert_taste(profile_id, dimension_type, dimension_key,
                      positive_delta, negative_delta, event_count)


def get_taste_weights_bulk(
    repo,
    profile_id: int,
    dimension_types: tuple[str, ...],
    role_id: int | None = None,
) -> dict[str, dict[str, float]]:
    """Every requested dimension in ONE query instead of one query each.

    The feed reads category, commodity and author on every request. Against a
    database a round trip away that was three trips for rows that live in the
    same table.
    """
    rows = repo.taste_rows(profile_id, dimension_types)
    grouped: dict[str, list] = {d: [] for d in dimension_types}
    for row in rows:
        grouped.setdefault(row.dimension_type, []).append(row)
    return {d: _weights_from_rows(grouped[d], d, role_id) for d in dimension_types}


def get_taste_weights(
    repo,
    profile_id: int,
    dimension_type: str,
    role_id: int | None = None,
) -> dict[str, float]:
    """
    Returns taste weights for a given dimension type.

    Processing applied in order:
    1. Exponential time decay (TASTE_DECAY_LAMBDA, ~30-day half-life).
    2. Net score = decayed_positive - negative_score × _NEG_DISCOUNT.
    3. Floor at _SCORE_FLOOR so no dimension is completely suppressed.
    4. Category only: confidence blend with role defaults until
       TASTE_BOOTSTRAP_EVENTS are accumulated.

    Returns a dict of {dimension_key: raw_score}.
    Caller normalises via log1p before using in the reranker.
    Returns {} for non-category dimensions with no data yet.
    """
    rows = repo.taste_rows(profile_id, (dimension_type,))

    return _weights_from_rows(rows, dimension_type, role_id)


def _weights_from_rows(rows, dimension_type: str, role_id: int | None) -> dict[str, float]:
    """Decay, floor and confidence-blend a set of UserPostTaste rows."""
    # Cold start — return role defaults for category, empty for other dimensions
    if not rows:
        if dimension_type == "category" and role_id is not None:
            return {k: float(v) for k, v in DEFAULT_TASTE.get(role_id, DEFAULT_TASTE[1]).items()}
        return {}

    scores: dict[str, float] = {}
    total_events = 0

    for row in rows:
        net = decayed_score(row.positive_score, row.negative_score, row.last_event_at, TASTE_DECAY_LAMBDA, _NEG_DISCOUNT)
        scores[row.dimension_key] = max(net, _SCORE_FLOOR)
        total_events += row.event_count

    # Confidence blend for category dimension
    if dimension_type == "category" and role_id is not None and total_events < TASTE_BOOTSTRAP_EVENTS:
        defaults = DEFAULT_TASTE.get(role_id, DEFAULT_TASTE[1])
        confidence = total_events / TASTE_BOOTSTRAP_EVENTS
        for key, default_val in defaults.items():
            learned = scores.get(key, _SCORE_FLOOR)
            scores[key] = confidence * learned + (1 - confidence) * float(default_val)

    return scores


def get_author_affinity(decayed_net_score: float) -> float:
    """
    Converts a decayed author taste score (output of get_taste_weights for
    dimension_type='author') into a [1.0, AUTHOR_AFFINITY_MAX] reranker multiplier.

    Uses log1p compression so early interactions have meaningful impact.
    Reaches AUTHOR_AFFINITY_MAX at AUTHOR_AFFINITY_SATURATION score.
    Returns 1.0 (no boost) when score <= 0.

    Example values:
      score=0   → 1.00  (never interacted with this author)
      score=5   → ~1.09 (one save, some decay)
      score=20  → 1.20  (saturation — max boost)
      score=100 → 1.20  (capped)
    """
    if decayed_net_score <= 0:
        return 1.0
    normalized = math.log1p(decayed_net_score) / math.log1p(AUTHOR_AFFINITY_SATURATION)
    return 1.0 + (AUTHOR_AFFINITY_MAX - 1.0) * min(normalized, 1.0)


def seed_taste_from_role(repo, profile_id: int, role_id: int) -> None:
    """
    Inserts initial category rows using role-seeded defaults.
    ON CONFLICT DO NOTHING — never overwrites existing learned data.
    Intended for user onboarding; not called automatically by record_interaction.
    """
    repo.seed_taste_rows(profile_id, DEFAULT_TASTE.get(role_id, DEFAULT_TASTE[1]))
