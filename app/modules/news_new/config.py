"""
news_new — central config for the whole module.

Single source of truth for: the 10-factor taxonomy, the role-relevancy matrix,
the closed enum sets, and every provider/LLM tunable. No DB lookups — categories
and role weights are plain Python dicts so they can be edited without a migration.
The ingestion, intelligence, and (later) recommendation slices all read from here.

API keys are NOT here — they come from app.core.config.settings (env / .env).
"""

# --------------------------------------------------------------------------- #
# Taxonomy — the 10 factors. These ARE the news categories. Assigned only by
# our classifier; provider categories are never mapped onto these.
# --------------------------------------------------------------------------- #
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

# --------------------------------------------------------------------------- #
# Relevancy matrix — role weights per factor (slug-keyed). role_relevance is
# COMPUTED from this in code, never produced by the LLM.
# --------------------------------------------------------------------------- #
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

# Role id -> name (1=Trader, 2=Broker, 3=Exporter), matches the platform roles.
ROLE_NAMES: dict[int, str] = {1: "trader", 2: "broker", 3: "exporter"}

# --------------------------------------------------------------------------- #
# Closed enum sets — enforced in prompt + code + (optionally) DB CHECK.
# --------------------------------------------------------------------------- #
PRIMARY_FACTORS: frozenset[str] = frozenset(RELEVANCY_MATRIX.keys())
GEO_CATEGORIES: frozenset[str] = frozenset({"global", "domestic", "regional"})
IMPACT_DIRECTIONS: frozenset[str] = frozenset({"positive", "neutral", "negative"})

# --------------------------------------------------------------------------- #
# Article intelligence lifecycle (status on RawArticle)
# --------------------------------------------------------------------------- #
STATUS_PENDING = "pending"
STATUS_ENRICHED = "enriched"
STATUS_FAILED = "failed"

# --------------------------------------------------------------------------- #
# Provider: GNews (free tier today; paid for production — free is non-commercial)
# --------------------------------------------------------------------------- #
GNEWS_BASE = "https://gnews.io/api/v4/search"
GNEWS_DEFAULT_QUERY = "commodity AND (export OR import OR price OR tariff)"
GNEWS_DEFAULT_COUNTRY = "in"    # used for manual single-query ingest; per-query in the pool
# `country` is NOT here — each query in news_queries.py controls its own
# (string -> domestic bias, None -> global). Manual ingest uses GNEWS_DEFAULT_COUNTRY.
GNEWS_PARAMS: dict = {
    "lang": "en",
    "max": 10,                  # free-tier ceiling (paid raises this)
    "in": "title,description",  # precision: ignore body-text false hits
    "sortby": "publishedAt",    # freshness
}
GNEWS_TIMEOUT_S = 30

# How many queries from the rotation pool to run per scheduled ingest.
# QUOTA: free tier = 100 requests/day. At a 30-min cadence (48 runs/day),
# 2 queries/run = 96 requests/day — just under the cap. Raising this means
# either fewer runs/day or a paid plan. Each query = up to `max` (10) articles.
GNEWS_QUERIES_PER_RUN = 2

# --------------------------------------------------------------------------- #
# Enrichment: Groq (OpenAI-compatible). One combined call per article.
# --------------------------------------------------------------------------- #
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# llama-3.1-8b-instant is on Groq's deprecation list (2026-06-17). Fall back to
# openai/gpt-oss-20b when it stops answering.
GROQ_MODEL = "llama-3.1-8b-instant"
GROQ_FALLBACK_MODEL = "openai/gpt-oss-20b"
GROQ_TEMPERATURE = 0.2
GROQ_TIMEOUT_S = 60
GROQ_MAX_RETRIES = 5

# Pacing — stay under the free limits (30 req/min, 6K tokens/min; ~1.5K/call).
# 2–3 articles/min is safe; 4/min (~6K tpm) is the hard ceiling.
ENRICH_ARTICLES_PER_MIN = 2.0
# How many pending articles to enrich per scheduled run (bounds a single job).
ENRICH_BATCH_LIMIT = 20

# Cap the content slice sent to the LLM to keep token cost predictable.
LLM_CONTENT_CHAR_CAP = 1000

# Archive: articles older than this many days are soft-deleted (is_active=False).
ARCHIVE_AFTER_DAYS = 30

# --------------------------------------------------------------------------- #
# System prompt — the LLM returns classification + summary + impact ONLY.
# It must NOT return role_relevance (that's computed from RELEVANCY_MATRIX).
# --------------------------------------------------------------------------- #
SYSTEM_PROMPT = f"""You are a commodity-trade news analyst. Read the article fields and return ONLY a JSON object (no prose, no markdown) with exactly these keys:

{{
  "primary_factor": one of {sorted(PRIMARY_FACTORS)},
  "factor_scores": [{{"factor": <slug>, "score": <0..1>}}],   // top 2-3 only
  "geo_category": one of ["global","domestic","regional"],
  "summary_bullets": [<string>, <string>, <string>],          // 3 concise points
  "impact": {{
      "direction": one of ["positive","neutral","negative"],
      "score": <0..10>,
      "factor": <short label, e.g. "Government policy">,
      "explanation": <one sentence>
  }}
}}

Definitions of primary_factor slugs:
- policy_regulation: govt policy, regulators, rules, tariffs, duties, bans.
- geopolitical_macro: war, sanctions, macro shocks, currency, cross-border events.
- supply_disruptions: weather, crop, logistics, port, production shocks.
- financial_mechanics: interest rates, credit, margins, financing mechanics.
- structural_shifts: long-run industry/tech/structural change.
- long_term_demand: slow demand trends, consumption shifts.
- deal_flow: deals, tenders, contracts, trade volumes, market participation.
- price_volatility: price moves, sentiment, volatility.
- local_operational: local mandi/market operational events.
- indirect_general: tangential or general news.

geo_category: domestic = single-country home market; regional = sub-national/local; global = cross-border/international.
Do not invent role weightings. Do not output anything except the JSON object."""


def role_relevance_for(slug: str) -> dict[str, float]:
    """Deterministic role_relevance lookup from the matrix (copy, never mutate)."""
    return dict(RELEVANCY_MATRIX[slug])
