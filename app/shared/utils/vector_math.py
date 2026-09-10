"""
Shared vector-similarity math — the same weighted-cosine-similarity formula
was independently reimplemented in modules/post/recommendation/vectors.py and
inlined directly (via np.linalg.norm) in modules/groups/recommendation/vectors.py.
Consolidated here; module-specific vector *construction* (build_post_vector,
build_group_vector, build_candidate_vector, ...) stays where it is — those
encode domain-specific dimension layouts, not something to unify.
"""
from __future__ import annotations

import numpy as np


def weighted_cosine_similarity(
    u: list[float],
    v: list[float],
    weights: list[float] | None = None,
) -> float:
    """
    Cosine similarity between u and v, optionally weighting each dimension
    before comparing (weights=None = plain unweighted cosine similarity).
    Returns 0.0 when either vector norms to zero.
    """
    a = np.array(u, dtype=float)
    b = np.array(v, dtype=float)
    if weights is not None:
        w = np.array(weights, dtype=float)
        a = a * w
        b = b * w
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    if norm == 0.0:
        return 0.0
    return float(np.dot(a, b) / norm)
