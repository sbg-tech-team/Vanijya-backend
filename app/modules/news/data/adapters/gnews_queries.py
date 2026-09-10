"""
GNews rotation query pool for the news module.

Each entry: {"q": <query string>, "country": "in" | None}
  country="in"  → India-biased results (domestic stories)
  country=None  → global coverage (no country filter)

Pool size: 12 queries.
At GNEWS_QUERIES_PER_RUN=2 and a 30-min ingest cadence (48 runs/day),
total daily API calls = 96 — just under the free-tier limit of 100.
Each query yields up to 10 articles (GNews free-tier max).

Rotation: select_queries_for_run() in gnews.py slices 2 queries per run
by time-slot so all 12 are covered evenly over the day.
"""
from __future__ import annotations

QUERY_POOL: list[dict] = [
    # policy_regulation — domestic
    {
        "q": "India commodity export import ban tariff duty regulation",
        "country": "in",
    },
    # supply_disruptions — domestic
    {
        "q": "India crop harvest monsoon yield production shortage",
        "country": "in",
    },
    # price_volatility — domestic
    {
        "q": "India commodity price mandi market futures",
        "country": "in",
    },
    # deal_flow — domestic
    {
        "q": "India commodity export tender contract shipment volume",
        "country": "in",
    },
    # local_operational
    {
        "q": "India agriculture mandi APMC grain oilseed arrival market",
        "country": "in",
    },
    # financial_mechanics — domestic
    {
        "q": "India commodity futures exchange margin credit financing",
        "country": "in",
    },
    # specific commodities — domestic
    {
        "q": "rice wheat sugar cotton soybean oil export import India",
        "country": "in",
    },
    # structural / long-term demand — domestic
    {
        "q": "India food agriculture industry demand consumption policy trend",
        "country": "in",
    },
    # geopolitical_macro — global
    {
        "q": "geopolitical commodity trade war sanction currency inflation global",
        "country": None,
    },
    # supply_disruptions — global
    {
        "q": "global commodity supply chain logistics port disruption freight",
        "country": None,
    },
    # policy_regulation — global (affects Indian exporters)
    {
        "q": "global commodity trade restriction export ban regulation policy",
        "country": None,
    },
    # price signals — global
    {
        "q": "commodity price crude oil metal grain soybean global trade market",
        "country": None,
    },
]
