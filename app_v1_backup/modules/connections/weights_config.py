# ─── Vector Boost Weights ────────────────────────────────────────────────────
COMMODITY_BOOST = 0.9
ROLE_BOOST      = 1.5
GEO_BOOST       = 3.0
QTY_BOOST       = 1.0   # tune upward to weight quantity scale-matching more
QTY_REF_MAX     = 1_000_000  # log ceiling: log1p(1M) ≈ 13.8 — anything above maps to 1.0

# ─── Commodities (fixed — never reorder, only append new ones at the end) ────
ALL_COMMODITIES = [
    "cotton",
    "rice",
    "sugar",
    # add new commodities here at the bottom only
]

# ─── Role Definitions ─────────────────────────────────────────────────────────
# AFFINITY  → what each role WANTS  (used in query/WANT vector)
# OFFERS    → what each role IS     (used in stored/IS vector)
# Dims order must stay fixed: [broker, exporter, trader]

ROLE_DIMS = ["broker", "exporter", "trader"]

ROLE_AFFINITY = {
    "trader":   {"broker": 0.55, "exporter": 0.30, "trader": 0.20},
    "broker":   {"broker": 0.33, "exporter": 0.33, "trader": 0.33},
    "exporter": {"broker": 0.70, "exporter": 0.20, "trader": 0.30},
}

ROLE_OFFERS = {
    "trader":   {"broker": 0.0, "exporter": 0.0, "trader": 1.0},
    "broker":   {"broker": 1.0, "exporter": 0.0, "trader": 0.0},
    "exporter": {"broker": 0.0, "exporter": 1.0, "trader": 0.0},
}