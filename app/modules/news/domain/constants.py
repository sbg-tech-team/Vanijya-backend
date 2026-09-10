"""
Domain-level constants for the news module.

Pure Python dicts / frozensets — no imports outside stdlib.
Imported by data/adapters/groq.py (enrichment) and recommendation/engine.py (ranking).
Source of truth: app_old/modules/news_new/config.py
"""
from __future__ import annotations

CATEGORIES: list[dict] = [
    {"id": 1,  "slug": "policy_regulation",   "name": "Policy & Regulation",
     "description": "Govt policy, regulators, rules, tariffs, duties, bans."},
    {"id": 2,  "slug": "geopolitical_macro",  "name": "Geopolitical & Macro Shocks",
     "description": "War, sanctions, macro shocks, currency, cross-border events."},
    {"id": 3,  "slug": "supply_disruptions",  "name": "Supply-side Disruptions",
     "description": "Weather, crop, logistics, port, production shocks."},
    {"id": 4,  "slug": "financial_mechanics", "name": "Financial & Market Mechanics",
     "description": "Interest rates, credit, margins, financing mechanics."},
    {"id": 5,  "slug": "structural_shifts",   "name": "Structural & Industrial Shifts",
     "description": "Long-run industry/tech/structural change."},
    {"id": 6,  "slug": "long_term_demand",    "name": "Long-term Demand Trends",
     "description": "Slow demand trends, consumption shifts."},
    {"id": 7,  "slug": "deal_flow",           "name": "Market Participation & Deal Flow",
     "description": "Deals, tenders, contracts, trade volumes, market participation."},
    {"id": 8,  "slug": "price_volatility",    "name": "Price Volatility & Sentiment",
     "description": "Price moves, sentiment, volatility."},
    {"id": 9,  "slug": "local_operational",   "name": "Local Operational Events",
     "description": "Local mandi/market operational events."},
    {"id": 10, "slug": "indirect_general",    "name": "Indirect / General News",
     "description": "Tangential or general news."},
]

SLUG_TO_ID: dict[str, int] = {c["slug"]: c["id"] for c in CATEGORIES}
ID_TO_SLUG: dict[int, str] = {c["id"]: c["slug"] for c in CATEGORIES}
SLUG_TO_NAME: dict[str, str] = {c["slug"]: c["name"] for c in CATEGORIES}

RELEVANCY_MATRIX: dict[str, dict[str, float]] = {
    "policy_regulation":   {"trader": 9.0, "broker": 9.2, "exporter": 9.8},
    "geopolitical_macro":  {"trader": 8.7, "broker": 8.4, "exporter": 9.5},
    "supply_disruptions":  {"trader": 7.3, "broker": 9.0, "exporter": 8.8},
    "financial_mechanics": {"trader": 5.8, "broker": 6.8, "exporter": 7.5},
    "structural_shifts":   {"trader": 4.2, "broker": 6.2, "exporter": 6.8},
    "long_term_demand":    {"trader": 3.2, "broker": 4.5, "exporter": 5.8},
    "deal_flow":           {"trader": 6.5, "broker": 9.3, "exporter": 7.2},
    "price_volatility":    {"trader": 8.5, "broker": 9.0, "exporter": 7.0},
    "local_operational":   {"trader": 5.5, "broker": 8.5, "exporter": 6.8},
    "indirect_general":    {"trader": 4.5, "broker": 5.5, "exporter": 5.8},
}

PRIMARY_FACTORS: frozenset[str] = frozenset(RELEVANCY_MATRIX.keys())
