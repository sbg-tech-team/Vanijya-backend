"""
GNews rotation pool for Vanijyaa ingestion — platform-specific commodity lanes.

Each entry: {"q": <GNews boolean query>, "country": "in" | None}
    country="in"  -> biases domestic results (feeds geo_category=domestic)
    country=None  -> global coverage (no country filter)

The scheduled job rotates through this pool a few queries per run (see
GNEWS_QUERIES_PER_RUN in config.py) so the whole list is covered over the day
without blowing the free-tier 100-requests/day budget.

Prune / extend to match the commodities actually live on the platform.
"""

QUERIES: list[dict] = [
    # --- Commodity lanes (supply_disruptions / price_volatility / deal_flow) ---
    {"q": '"rice export" OR "basmati" OR "rice price" OR "rice quota"',        "country": "in"},
    {"q": '"wheat export" OR "wheat price" OR "wheat import" OR "atta"',       "country": "in"},
    {"q": '"sugar export" OR "sugar quota" OR "sugar price" OR ethanol',       "country": "in"},
    {"q": '"edible oil" AND (import OR duty OR price OR "palm oil")',          "country": "in"},
    {"q": '(pulses OR chana OR tur OR "arhar" OR lentil OR urad) AND (price OR import OR export)', "country": "in"},
    {"q": '(cotton OR "cotton yarn" OR kapas) AND (export OR price OR MSP)',   "country": "in"},
    {"q": '(turmeric OR cumin OR jeera OR "black pepper" OR cardamom) AND price', "country": "in"},
    {"q": '(onion OR potato OR tomato) AND (price OR export OR ban OR stock)', "country": "in"},
    {"q": '(maize OR corn OR soybean OR soymeal) AND (export OR price OR feed)', "country": "in"},
    {"q": '(tea OR coffee) AND (export OR price OR auction)',                  "country": "in"},
    {"q": '(guar OR "guar gum" OR castor OR groundnut) AND (export OR price)', "country": "in"},

    # --- Policy & regulation (policy_regulation) ---
    {"q": '"export ban" OR "export duty" OR "minimum export price" OR "stock limit"', "country": "in"},
    {"q": '("import duty" OR tariff OR cess) AND (agri OR commodity OR food)', "country": "in"},
    {"q": 'MSP OR "minimum support price" OR procurement',                    "country": "in"},
    {"q": 'DGFT OR "foreign trade policy" OR APEDA OR "agri export"',          "country": "in"},
    {"q": 'FCI OR "Food Corporation of India" OR "buffer stock"',             "country": "in"},
    {"q": 'SEBI AND (commodity OR derivatives OR MCX OR NCDEX OR futures)',    "country": "in"},

    # --- Macro / geopolitical / global price (geopolitical_macro / price_volatility) ---
    {"q": '"crude oil" AND (price OR OPEC OR Brent)',                         "country": None},
    {"q": 'rupee AND (dollar OR depreciation OR RBI OR forex)',               "country": "in"},
    {"q": '("freight rates" OR shipping OR container) AND ("Red Sea" OR port OR cargo)', "country": None},
    {"q": '"commodity prices" AND (global OR rally OR surge OR fall)',        "country": None},
    {"q": 'monsoon AND India AND (crop OR rainfall OR sowing OR kharif OR rabi)', "country": "in"},

    # --- Deal flow / trade (deal_flow) ---
    {"q": 'tender AND (wheat OR rice OR sugar OR "edible oil" OR import OR export)', "country": "in"},
    {"q": '("export deal" OR "trade agreement" OR FTA) AND (commodity OR agri)', "country": None},
    {"q": '(port OR shipment OR cargo) AND (India OR export) AND (congestion OR delay OR volume)', "country": "in"},

    # --- Structural / inputs / local (structural_shifts / local_operational) ---
    {"q": '(fertiliser OR fertilizer OR urea OR DAP) AND (subsidy OR price OR supply)', "country": "in"},
    {"q": 'mandi AND (price OR arrival OR APMC)',                             "country": "in"},
    {"q": '(warehouse OR "cold storage" OR logistics) AND (agri OR commodity)', "country": "in"},
]
