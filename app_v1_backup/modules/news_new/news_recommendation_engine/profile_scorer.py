"""
Layer 2 profile score — commodity affinity + state affinity.

No role dependency: role is already captured by Layer 1 (RELEVANCY_MATRIX).
This layer answers: given two users with the same role, how should their feeds
differ based on what they trade and where they operate?

Inputs (all from Profile / Business / Commodity — zero interaction history):
  user_commodities   list[str]    commodity names from profile (e.g. ["rice", "cotton"])
  user_state         str | None   business.state (e.g. "Punjab")
  enriched           EnrichedArticle with commodity_tags and state_tags populated by LLM

Output: profile_boost float in [0.0, 0.35]
  Applied as: final_score = layer1_score * (1 + profile_boost)
  Multiplicative so Layer 1 remains the relevance floor — commodity match cannot
  rescue a topically irrelevant article.
"""
from __future__ import annotations

from app.modules.news_new.intelligence.models import EnrichedArticle

# α: commodity overlap contribution to boost (dominant signal)
COMMODITY_WEIGHT = 0.25
# β: state match contribution to boost (secondary signal)
STATE_WEIGHT = 0.10
# Max possible boost = COMMODITY_WEIGHT + STATE_WEIGHT = 0.35


def compute_commodity_score(
    user_commodities: list[str],
    article_tags: list[str],
) -> float:
    """
    Jaccard similarity between user's traded commodities and article commodity tags.
    Both sides are lowercased + stripped before comparison.
    Returns 0.0 if either list is empty.
    """
    if not user_commodities or not article_tags:
        return 0.0
    user_set = {c.lower().strip() for c in user_commodities}
    article_set = {t.lower().strip() for t in article_tags}
    intersection = len(user_set & article_set)
    union = len(user_set | article_set)
    return intersection / union if union > 0 else 0.0


def compute_state_score(
    user_state: str | None,
    article_state_tags: list[str],
) -> float:
    """
    1.0 if the user's business state is explicitly mentioned in the article, 0.0 otherwise.
    Returns 0.0 if user_state is None or article has no state tags.
    """
    if not user_state or not article_state_tags:
        return 0.0
    needle = user_state.lower().strip()
    return 1.0 if needle in {s.lower().strip() for s in article_state_tags} else 0.0


def compute_profile_boost(
    user_commodities: list[str],
    user_state: str | None,
    enriched: EnrichedArticle | None,
) -> float:
    """
    Returns a boost in [0.0, 0.35].
    Use as: final_score = layer1_score * (1 + profile_boost)
    """
    if not enriched:
        return 0.0
    commodity_score = compute_commodity_score(user_commodities, enriched.commodity_tags or [])
    state_score = compute_state_score(user_state, enriched.state_tags or [])
    return COMMODITY_WEIGHT * commodity_score + STATE_WEIGHT * state_score


def apply_profile_boost(layer1_score: float, profile_boost: float) -> float:
    """Multiplicative application: final = layer1 * (1 + boost), rounded to 4dp."""
    return round(layer1_score * (1.0 + profile_boost), 4)
