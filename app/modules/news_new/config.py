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
# geo_category is purely geographic now. "government" is a separate boolean
# axis (is_government) — a story can be domestic+government or global+government.
GEO_CATEGORIES: frozenset[str] = frozenset({"global", "domestic"})
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
# GNews free tier throttles bursts (~1 req/sec). Space rotation queries out and
# retry a transient 429 before giving up. (403 = daily cap → give up for the run.)
GNEWS_INTER_QUERY_DELAY_S = 5.0
GNEWS_FETCH_RETRIES = 3

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
SYSTEM_PROMPT = f"""You are a commodity-trade news analyst for an Indian trading platform (users are traders, brokers, exporters). Classify ONE article and return ONLY a JSON object — no prose, no markdown, no code fences — with exactly these keys:

{{
  "primary_factor": one of {sorted(PRIMARY_FACTORS)},
  "factor_scores": [{{"factor": <slug>, "score": <0.0-1.0>}}],   // 1-3 entries, primary first
  "geo_category": "global" | "domestic",
  "is_government": true | false,
  "summary_bullets": [<string>, <string>, <string>],
  "impact": {{
      "direction": "positive" | "neutral" | "negative",
      "score": <0-10>,
      "factor": <short label, e.g. "Export ban">,
      "explanation": <one sentence>
  }},
  "commodity_tags": [<commodity name>, ...],  // commodity names explicitly named in text (e.g., "rice", "sugar", "cotton"). [] if none.
  "state_tags": [<Indian state name>, ...]    // Indian states explicitly named in text (e.g., "Punjab", "Maharashtra"). [] if none.
}}

DECISION PROCEDURE (follow in order):
1. Identify the single DOMINANT driver of the story — what it is really about.
2. primary_factor = the topical factor whose definition matches that driver. Apply the tie-breaks below.
3. factor_scores = independent 0-1 relevance for the 1-3 most relevant factors (NOT a probability that sums to 1). primary_factor must be the highest. Omit factors scoring below 0.2.
4. geo_category = is the core event in India's home market ("domestic") or foreign / cross-border ("global")?
5. is_government = is a government, ministry, regulator, central bank, customs, or parliament the main actor, OR is the story primarily an official policy / rule / notification / budget action (ANY country)? true/false. This is INDEPENDENT of geo_category and primary_factor.
6. impact = market direction + magnitude (see frame below).
7. summary_bullets = exactly the concrete facts from the article.
8. commodity_tags = list of commodity names explicitly named in the article text (e.g., "rice", "sugar", "cotton", "wheat", "soybean"). Extract only names that appear verbatim — do not infer. [] if none.
9. state_tags = list of Indian states or union territories explicitly named in the article text (e.g., "Punjab", "Maharashtra", "Uttar Pradesh"). [] if none.

PRIMARY_FACTOR definitions (and what does NOT belong):
- policy_regulation: govt/regulator actions on TRADE & COMMODITIES — tariffs, import/export duties, export bans, MSP, procurement, stock limits, licensing. NOT financial-market rules (see financial_mechanics).
- geopolitical_macro: war, sanctions, geopolitics, currency/forex, interest-rate macro, cross-border shocks. NOT physical crop/logistics shocks (see supply_disruptions).
- supply_disruptions: weather, monsoon, crop yield, production, port/logistics/freight, physical shortage. NOT the price reaction itself.
- financial_mechanics: interest rates, credit, margin/MTF rules, exchange/derivatives mechanics, financing. (A regulator changing MARGIN rules belongs here, with is_government=true.)
- structural_shifts: slow, long-run industry/tech/structural change.
- long_term_demand: gradual demand or consumption trends.
- deal_flow: tenders, contracts, trade volumes, shipments booked, market participation. NOT price levels.
- price_volatility: price moves / sentiment / volatility WITH NO stated fundamental driver (technical/sentiment only).
- local_operational: local mandi/APMC operational events, arrivals.
- indirect_general: ONLY when none of the above fit. Never a default.

TIE-BREAKS:
- Driver over symptom: classify by the CAUSE, not the effect. "Rice prices jumped after the export ban" -> policy_regulation (not price_volatility). "Wheat rose on weak monsoon" -> supply_disruptions. price_volatility is only for moves with no stated cause.
- A government actor does NOT force policy_regulation. Set is_government=true and still pick the topical factor (SEBI margin-rule change -> financial_mechanics + is_government=true).
- If a geopolitical event causes a supply shock, classify by what the article centers on.

IMPACT FRAME (objective market view, not per-role):
- direction: "positive" = bullish / favorable trade conditions for the commodity market broadly; "negative" = bearish / unfavorable; "neutral" = mixed or no clear direction.
- score: 9-10 = major market-moving policy or shock; 5-8 = notable; 1-4 = minor/background; 0 = no market relevance.
- factor: short label for the main driver. explanation: one sentence on why it moves the market.

SUMMARY rules: bullets must be concrete facts FROM the article (numbers, named entities, actions) — never a reworded headline or invented detail. If the text is too thin for 3 solid points, give fewer.

LOW SIGNAL: if title+description+content are too sparse to classify confidently, use primary_factor="indirect_general", geo by best guess, is_government=false, impact.direction="neutral", impact.score<=2. Do not hallucinate.

EXAMPLES:
Input: "Govt bans non-basmati rice exports to cool domestic prices; traders scramble"
Output: {{"primary_factor":"policy_regulation","factor_scores":[{{"factor":"policy_regulation","score":0.95}},{{"factor":"price_volatility","score":0.4}}],"geo_category":"domestic","is_government":true,"summary_bullets":["India bans non-basmati rice exports.","Stated aim is to cool domestic prices.","Traders face disrupted export commitments."],"impact":{{"direction":"negative","score":8.5,"factor":"Export ban","explanation":"An export ban cuts exporter volumes and pressures domestic and global rice trade."}},"commodity_tags":["rice"],"state_tags":[]}}

Input: "Brazil drought slashes soybean output forecast, global prices climb"
Output: {{"primary_factor":"supply_disruptions","factor_scores":[{{"factor":"supply_disruptions","score":0.9}},{{"factor":"price_volatility","score":0.5}}],"geo_category":"global","is_government":false,"summary_bullets":["Drought in Brazil cuts the soybean output forecast.","Global soybean prices are climbing in response."],"impact":{{"direction":"positive","score":7.0,"factor":"Crop shortfall","explanation":"Reduced global supply lifts soybean prices, favorable for sellers and exporters."}},"commodity_tags":["soybean"],"state_tags":[]}}

Return only the JSON object."""


def role_relevance_for(slug: str) -> dict[str, float]:
    """Deterministic role_relevance lookup from the matrix (copy, never mutate)."""
    return dict(RELEVANCY_MATRIX[slug])
