"""
Group embedding + similarity utilities.

Layout (11 dims — mirrors user_embeddings):
  [0:3]   commodity  (3 dims, one-hot boosted)
  [3:6]   role       (3 dims, IS/OFFERS encoding averaged across target_roles)
  [6:9]   geo        (3 dims, unit-sphere Cartesian × GEO_BOOST)
  [9:11]  zeros      (groups have no qty range; reserved for future use)

Recommendation pipeline:
  user WANT vector (build_query_vector) <=> group IS vector (build_group_vector)
  cosine_sim  ×0.75  +  activity_score  ×0.25  →  final_score
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

from app.modules.connections.weights_config import (
    ALL_COMMODITIES,
    COMMODITY_BOOST,
    GEO_BOOST,
    ROLE_BOOST,
    ROLE_DIMS,
    ROLE_OFFERS,
)
from app.modules.connections.encoding.vector import encode_commodity, encode_geo

# ---------------------------------------------------------------------------
# Role encoding for groups
# ---------------------------------------------------------------------------

def _encode_group_roles(target_roles: list[str]) -> np.ndarray:
    """
    Average the IS (OFFERS) vectors of all target_roles.
    A group targeting ["trader","broker"] sits between both profiles.
    """
    if not target_roles:
        return np.zeros(len(ROLE_DIMS))

    vecs = []
    for role in target_roles:
        if role in ROLE_OFFERS:
            offers = ROLE_OFFERS[role]
            vecs.append(np.array([offers[d] for d in ROLE_DIMS]) * ROLE_BOOST)

    return np.mean(vecs, axis=0) if vecs else np.zeros(len(ROLE_DIMS))


# ---------------------------------------------------------------------------
# Group IS vector
# ---------------------------------------------------------------------------

def build_group_vector(
    commodity_list: list[str],
    target_roles: list[str],
    lat: float,
    lon: float,
) -> list[float]:
    """
    Build the 11-dim IS vector for a group.
    Stored in group_embeddings.embedding.
    """
    comm_vec = encode_commodity(commodity_list)          # 3 dims
    role_vec = _encode_group_roles(target_roles)         # 3 dims
    geo_vec = encode_geo(lat, lon) * GEO_BOOST           # 3 dims
    qty_vec = np.zeros(2)                                 # 2 dims (unused for groups)

    return np.hstack([comm_vec, role_vec, geo_vec, qty_vec]).tolist()


# ---------------------------------------------------------------------------
# Similarity & reranking
# ---------------------------------------------------------------------------

def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [−1, 1]. Returns 0 for zero-norm vectors."""
    va, vb = np.array(a, dtype=float), np.array(b, dtype=float)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


def compute_activity_score(
    messages_24h: int,
    active_members_7d: int,
    member_growth_7d: int,
) -> float:
    """
    Soft-normalise activity signals to [0, 1] via log scale.
    Ceiling at ~100 raw units so very large groups don't dominate.
    """
    raw = messages_24h * 0.4 + active_members_7d * 0.4 + max(member_growth_7d, 0) * 0.2
    return math.log1p(raw) / math.log1p(100)


def compute_final_score(cosine_sim: float, activity_score: float) -> float:
    """Weighted blend: 75 % semantic, 25 % activity."""
    return round(cosine_sim * 0.75 + activity_score * 0.25, 4)


# ---------------------------------------------------------------------------
# Match reasons (human-readable)
# ---------------------------------------------------------------------------

def build_match_reasons(
    user_commodities: list[str],
    user_role: str,
    group_commodities: list[str],
    group_target_roles: list[str],
    cosine_sim: float,
    act_score: float,
) -> list[str]:
    reasons: list[str] = []

    user_comm = {c.lower() for c in user_commodities}
    grp_comm = {c.lower() for c in (group_commodities or [])}
    if user_comm & grp_comm:
        reasons.append("Matches your commodities")

    grp_roles = {r.lower() for r in (group_target_roles or [])}
    if user_role.lower() in grp_roles:
        reasons.append("Targets your role")

    if cosine_sim > 0.70:
        reasons.append("Highly relevant to your profile")

    if act_score > 0.35:
        reasons.append("Active community")

    return reasons or ["Recommended for you"]
