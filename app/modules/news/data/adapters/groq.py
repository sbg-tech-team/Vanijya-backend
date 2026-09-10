"""
Groq Llama adapter — implements INewsEnricher.

One HTTP call per article to Groq's OpenAI-compatible endpoint.
Retries up to GROQ_MAX_RETRIES; falls back to GROQ_FALLBACK_MODEL after
primary model consistently fails.
Role scores (role_trader/broker/exporter) are computed from the RELEVANCY_MATRIX
deterministically — never produced by the LLM.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone

import requests

from app.core.config import settings
from app.modules.news.domain.constants import PRIMARY_FACTORS, RELEVANCY_MATRIX
from app.modules.news.domain.entities import EnrichedArticle, RawArticle
from app.modules.news.domain.exceptions import EnrichmentError
from app.modules.news.domain.interfaces.enricher import INewsEnricher

log = logging.getLogger(__name__)

# ── Enricher constants ────────────────────────────────────────────────────────

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_MODEL = "llama-3.1-8b-instant"
_FALLBACK_MODEL = "openai/gpt-oss-20b"
_TEMPERATURE = 0.2
_TIMEOUT_S = 60
_MAX_RETRIES = 5
_CONTENT_CHAR_CAP = 1000

_SYSTEM_PROMPT = f"""You are a commodity-trade news analyst for an Indian trading platform (users are traders, brokers, exporters). Classify ONE article and return ONLY a JSON object — no prose, no markdown, no code fences — with exactly these keys:

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
  "commodity_tags": [<commodity name>, ...],
  "state_tags": [<Indian state name>, ...]
}}

DECISION PROCEDURE (follow in order):
1. Identify the single DOMINANT driver of the story — what it is really about.
2. primary_factor = the topical factor whose definition matches that driver. Apply the tie-breaks below.
3. factor_scores = independent 0-1 relevance for the 1-3 most relevant factors (NOT a probability that sums to 1). primary_factor must be the highest. Omit factors scoring below 0.2.
4. geo_category = is the core event in India's home market ("domestic") or foreign / cross-border ("global")?
5. is_government = is a government, ministry, regulator, central bank, customs, or parliament the main actor, OR is the story primarily an official policy / rule / notification / budget action (ANY country)? true/false. Independent of geo_category and primary_factor.
6. impact = market direction + magnitude.
7. summary_bullets = exactly the concrete facts from the article.
8. commodity_tags = commodity names explicitly named in the article text. Extract only verbatim names. [] if none.
9. state_tags = Indian states or union territories explicitly named in the article text. [] if none.

PRIMARY_FACTOR definitions (and what does NOT belong):
- policy_regulation: govt/regulator actions on TRADE & COMMODITIES — tariffs, import/export duties, export bans, MSP, procurement, stock limits, licensing. NOT financial-market rules (see financial_mechanics).
- geopolitical_macro: war, sanctions, geopolitics, currency/forex, interest-rate macro, cross-border shocks. NOT physical crop/logistics shocks (see supply_disruptions).
- supply_disruptions: weather, monsoon, crop yield, production, port/logistics/freight, physical shortage. NOT the price reaction itself.
- financial_mechanics: interest rates, credit, margin/MTF rules, exchange/derivatives mechanics, financing.
- structural_shifts: slow, long-run industry/tech/structural change.
- long_term_demand: gradual demand or consumption trends.
- deal_flow: tenders, contracts, trade volumes, shipments booked, market participation. NOT price levels.
- price_volatility: price moves / sentiment / volatility WITH NO stated fundamental driver (technical/sentiment only).
- local_operational: local mandi/APMC operational events, arrivals.
- indirect_general: ONLY when none of the above fit. Never a default.

TIE-BREAKS:
- Driver over symptom: classify by the CAUSE, not the effect. "Rice prices jumped after the export ban" -> policy_regulation (not price_volatility). "Wheat rose on weak monsoon" -> supply_disruptions. price_volatility is only for moves with no stated cause.
- A government actor does NOT force policy_regulation. Set is_government=true and still pick the topical factor.
- If a geopolitical event causes a supply shock, classify by what the article centers on.

IMPACT FRAME (objective market view, not per-role):
- direction: "positive" = bullish / favorable trade conditions broadly; "negative" = bearish / unfavorable; "neutral" = mixed or no clear direction.
- score: 9-10 = major market-moving; 5-8 = notable; 1-4 = minor/background; 0 = no market relevance.

SUMMARY rules: bullets must be concrete facts FROM the article (numbers, named entities, actions) — never a reworded headline or invented detail.

LOW SIGNAL: if title+description+content are too sparse to classify confidently, use primary_factor="indirect_general", geo by best guess, is_government=false, impact.direction="neutral", impact.score<=2. Do not hallucinate.

Return only the JSON object."""


class GroqEnricher(INewsEnricher):

    model = _MODEL

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or settings.GROQ_API_KEY

    # ── INewsEnricher ──────────────────────────────────────────────────────────

    def enrich(self, raw_article: RawArticle) -> EnrichedArticle:
        text = _build_text(raw_article)
        llm_output = self._call_with_retry(text)
        return _build_enriched_article(raw_article, llm_output)

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _call_with_retry(self, text: str) -> dict:
        model = _MODEL
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                raw = self._call_groq(text, model)
                parsed = _parse_json(raw)
                _validate(parsed)
                return parsed
            except (EnrichmentError, ValueError, KeyError) as exc:
                last_exc = exc
                wait = 2 ** attempt
                log.warning(
                    "Groq enrich attempt %d/%d failed (%s): %s — retrying in %ds",
                    attempt + 1, _MAX_RETRIES, model, exc, wait,
                )
                time.sleep(wait)
                # Switch to fallback model after first half of retries
                if attempt == _MAX_RETRIES // 2 - 1:
                    log.info("Switching to fallback model %s", _FALLBACK_MODEL)
                    model = _FALLBACK_MODEL

        raise EnrichmentError(
            f"Groq enrichment failed after {_MAX_RETRIES} retries: {last_exc}"
        )

    def _call_groq(self, text: str, model: str) -> str:
        if not self._api_key:
            raise RuntimeError("GROQ_API_KEY is not configured")

        payload = {
            "model": model,
            "temperature": _TEMPERATURE,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
        }
        try:
            r = requests.post(
                _GROQ_URL,
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=_TIMEOUT_S,
            )
            r.raise_for_status()
        except requests.HTTPError as exc:
            raise EnrichmentError(f"Groq HTTP error ({model}): {exc}") from exc
        except requests.RequestException as exc:
            raise EnrichmentError(f"Groq request error ({model}): {exc}") from exc

        content = r.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content:
            raise EnrichmentError(f"Groq returned empty content for model {model}")
        return content


# ── Module-level helpers ──────────────────────────────────────────────────────

def _build_text(article: RawArticle) -> str:
    parts = [f"Title: {article.title}"]
    if article.description:
        parts.append(f"Description: {article.description}")
    if article.content:
        content = article.content[:_CONTENT_CHAR_CAP]
        parts.append(f"Content: {content}")
    return "\n".join(parts)


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    # Strip markdown code fences if the model added them despite instructions
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM output is not valid JSON: {exc}\nRaw: {raw[:300]}") from exc


def _validate(data: dict) -> None:
    factor = data.get("primary_factor")
    if factor not in PRIMARY_FACTORS:
        raise ValueError(f"primary_factor {factor!r} not in PRIMARY_FACTORS")
    if data.get("geo_category") not in {"global", "domestic"}:
        raise ValueError(f"geo_category {data.get('geo_category')!r} invalid")
    impact = data.get("impact")
    if not isinstance(impact, dict):
        raise ValueError("impact must be a dict")
    if impact.get("direction") not in {"positive", "neutral", "negative"}:
        raise ValueError(f"impact.direction {impact.get('direction')!r} invalid")


def _build_enriched_article(raw: RawArticle, data: dict) -> EnrichedArticle:
    factor = data["primary_factor"]
    role_weights = RELEVANCY_MATRIX.get(factor, {"trader": 4.5, "broker": 5.5, "exporter": 5.8})
    impact = data.get("impact", {})

    return EnrichedArticle(
        id=uuid.uuid4(),
        raw_article_id=raw.id,
        primary_factor=factor,
        factor_scores=data.get("factor_scores"),
        geo_category=data.get("geo_category", "global"),
        is_government=bool(data.get("is_government", False)),
        commodity_tags=data.get("commodity_tags") or [],
        state_tags=data.get("state_tags") or [],
        summary_bullets=data.get("summary_bullets") or [],
        summary_long=None,
        impact_direction=impact.get("direction", "neutral"),
        impact_score=float(impact.get("score", 0)),
        impact_factor=impact.get("factor"),
        impact_explanation=impact.get("explanation"),
        role_trader=role_weights["trader"],
        role_broker=role_weights["broker"],
        role_exporter=role_weights["exporter"],
        model_version=_MODEL,
        generated_at=datetime.now(timezone.utc).replace(tzinfo=None),
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
