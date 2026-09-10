import numpy as np

from app.modules.post.post_recommendation_module.constants import (
    COMMODITY_ID_TO_IDX,
    ROLE_ID_TO_IDX,
    FEED_WEIGHTS,
    QTY_SCALE_MT,
    VECTOR_DIM,
)


def build_post_vector(
    commodity_id: int,
    target_role_ids: list[int] | None,
    lat: float,
    lon: float,
    is_deal: bool = False,
    commodity_quantity: float | None = None,
) -> list[float]:
    """
    Builds the 10-dim post vector stored in post_embeddings.
    commodity[0:3]  one-hot for post commodity
    role[3:6]       multi-hot for target_roles; all-ones if targeting everyone
    geo[6:9]        3D unit-sphere Cartesian from author lat/lon
    qty[9]          deal quantity normalised over QTY_SCALE_MT; zero for non-deal posts
    """
    commodity = np.zeros(3)
    idx = COMMODITY_ID_TO_IDX.get(commodity_id)
    if idx is not None:
        commodity[idx] = 1.0

    role = np.zeros(3)
    if target_role_ids:
        for rid in target_role_ids:
            r_idx = ROLE_ID_TO_IDX.get(rid)
            if r_idx is not None:
                role[r_idx] = 1.0
    else:
        role[:] = 1.0  # no restriction – targets all roles

    lat_r = np.radians(lat)
    lon_r = np.radians(lon)
    geo = np.array([
        np.cos(lat_r) * np.cos(lon_r),
        np.cos(lat_r) * np.sin(lon_r),
        np.sin(lat_r),
    ])

    qty = np.zeros(1)
    if is_deal and commodity_quantity is not None:
        qty[0] = min(float(commodity_quantity) / QTY_SCALE_MT, 1.0)

    return np.concatenate([commodity, role, geo, qty]).tolist()


def build_user_feed_vector(
    commodity_ids: list[int],
    role_id: int,
    lat: float,
    lon: float,
    commodity_quantity: float,
) -> list[float]:
    """
    Builds the 10-dim user vector used to query the recommendation engine.
    commodity[0:3]  averaged multi-hot
    role[3:6]       single-hot for user's own role
    geo[6:9]        3D unit-sphere Cartesian from user's location
    qty[9]          user's typical trade quantity normalised over QTY_SCALE_MT
    """
    commodity = np.zeros(3)
    valid_idxs = [COMMODITY_ID_TO_IDX[cid] for cid in commodity_ids if cid in COMMODITY_ID_TO_IDX]
    if valid_idxs:
        for idx in valid_idxs:
            commodity[idx] = 1.0
        commodity /= len(valid_idxs)

    role = np.zeros(3)
    r_idx = ROLE_ID_TO_IDX.get(role_id)
    if r_idx is not None:
        role[r_idx] = 1.0

    lat_r = np.radians(lat)
    lon_r = np.radians(lon)
    geo = np.array([
        np.cos(lat_r) * np.cos(lon_r),
        np.cos(lat_r) * np.sin(lon_r),
        np.sin(lat_r),
    ])

    qty = np.array([min(float(commodity_quantity) / QTY_SCALE_MT, 1.0)])

    return np.concatenate([commodity, role, geo, qty]).tolist()


def weighted_cosine_similarity(u: list[float], v: list[float]) -> float:
    """Applies FEED_WEIGHTS to both vectors before computing cosine similarity."""
    w = np.array(FEED_WEIGHTS)
    a = np.array(u) * w
    b = np.array(v) * w
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    if norm == 0.0:
        return 0.0
    return float(np.dot(a, b) / norm)
