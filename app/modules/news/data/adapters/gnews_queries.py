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

────────────────────────────────────────────────────────────────────────────
QUERY SYNTAX — read this before editing.

GNews ANDs every bare term, and `in=title,description` means all of them must
appear in the title or the description. Adding a word does not broaden a
query, it narrows it, and the narrowing is brutal:

    India commodity                          1034 results
    India commodity export                     41
    India commodity export price                4
    India commodity export import ban tariff duty regulation    0

The original pool was written as 6–9 bare keywords per entry, in the belief
that more terms meant wider coverage. Every one of the twelve returned zero,
so ingestion produced nothing, nothing new arrived for the 30-day archive job
to spare, and all three news feeds went blank while 2866 rows sat in the
table. It failed silently: no error, no quota warning, just `saved=0`.

So: ONE required anchor, then alternatives OR'd inside parentheses. Keep the
anchor to a single word. After changing anything here, run

    python _migration/check_news_queries.py

which fails if any query returns zero.
────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

QUERY_POOL: list[dict] = [
    # policy_regulation — domestic
    {
        "q": "India AND (tariff OR duty OR \"export ban\" OR \"import ban\")",
        "country": "in",
    },
    # supply_disruptions — domestic
    {
        "q": "India AND (crop OR harvest OR monsoon OR yield OR shortage)",
        "country": "in",
    },
    # price_volatility — domestic
    {
        "q": "India AND (mandi OR \"commodity price\" OR futures)",
        "country": "in",
    },
    # deal_flow — domestic
    {
        "q": "India AND (tender OR shipment OR contract OR consignment)",
        "country": "in",
    },
    # local_operational
    {
        "q": "India AND (APMC OR mandi OR grain OR oilseed)",
        "country": "in",
    },
    # financial_mechanics — domestic
    {
        "q": "India AND (MCX OR NCDEX OR \"commodity exchange\" OR margin)",
        "country": "in",
    },
    # specific commodities — domestic
    {
        "q": "India AND (rice OR wheat OR sugar OR cotton OR soybean)",
        "country": "in",
    },
    # structural / long-term demand — domestic
    {
        "q": "India AND (agriculture OR \"food processing\" OR \"farm sector\")",
        "country": "in",
    },
    # geopolitical_macro — global
    {
        "q": "commodity AND (sanction OR \"trade war\" OR tariff OR inflation)",
        "country": None,
    },
    # supply_disruptions — global
    {
        "q": "commodity AND (\"supply chain\" OR freight OR port OR logistics)",
        "country": None,
    },
    # policy_regulation — global (affects Indian exporters)
    {
        "q": "commodity AND (\"export ban\" OR restriction OR quota OR regulation)",
        "country": None,
    },
    # price signals — global
    {
        "q": "commodity AND (\"crude oil\" OR wheat OR copper OR soybean)",
        "country": None,
    },
]
