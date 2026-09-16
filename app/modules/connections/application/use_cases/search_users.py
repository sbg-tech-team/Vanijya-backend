"""
User search use cases — Section C of the original service.py.

Handles filtered user search and name/business autocomplete suggestions.
No FastAPI imports. Domain exceptions are raised instead of HTTPException.
"""
from __future__ import annotations

import re
from uuid import UUID


from app.modules.connections.recommendation.weights_config import ALL_COMMODITIES
# profile models are reached through the repository

# ── Search intent parsing ────────────────────────────────────────────────────
_KNOWN_ROLES = {"trader", "broker", "exporter"}
_ROLE_PLURAL = {"traders": "trader", "brokers": "broker", "exporters": "exporter"}
_KNOWN_COMMODITIES = set(ALL_COMMODITIES)
_CITY_PATTERN = re.compile(r'\b(?:in|from)\s+(\w+)', re.IGNORECASE)


from app.modules.connections.application.formatters import fmt_profile
from app.modules.connections.domain.interfaces.repository import IConnectionsRepository


def _parse_search_intent(q: str) -> dict:
    """
    Extracts role, commodity, city from free-text q so the frontend only needs
    one search box. Explicit params passed by the caller always take priority.

    "rice exporters in mumbai" -> role="exporter", commodity="rice", city="mumbai", name_q=None
    "ravi broker"              -> role="broker", commodity=None, city=None, name_q="ravi"
    """
    tokens = q.lower().split()
    role, commodity, city = None, None, None
    skip: set[str] = set()

    city_match = _CITY_PATTERN.search(q)
    if city_match:
        city = city_match.group(1).lower()
        skip.update(city_match.group(0).lower().split())

    remaining = []
    for token in tokens:
        if token in skip:
            continue
        normalized = _ROLE_PLURAL.get(token, token)
        if normalized in _KNOWN_ROLES:
            role = normalized
        elif token in _KNOWN_COMMODITIES:
            commodity = token
        else:
            remaining.append(token)

    return {
        "role":      role,
        "commodity": commodity,
        "city":      city,
        "name_q":    " ".join(remaining) or None,
    }


# ---------------------------------------------------------------------------
# Internal profile helpers
# ---------------------------------------------------------------------------



def search_users(
    repo: IConnectionsRepository,
    me: UUID,
    q: str | None = None,
    role: str | None = None,
    commodity: str | None = None,
    city: str | None = None,
    user_verified_only: bool = False,
    business_verified_only: bool = False,
    page: int = 1,
    limit: int = 20,
) -> dict:
    """
    Filtered user search against the real profile table.
    q                      — partial match on name / business_name
    role                   — exact match: trader | broker | exporter
    commodity              — partial match on commodity name
    city                   — partial match on city
    user_verified_only     — only return profiles where is_user_verified=True (KYC)
    business_verified_only — only return profiles where is_business_verified=True (KYB)
    Excludes the calling user. Supports pagination via page/limit.
    """
    if q and not any([role, commodity, city]):
        intent = _parse_search_intent(q)
        role      = role      or intent["role"]
        commodity = commodity or intent["commodity"]
        city      = city      or intent["city"]
        q         = intent["name_q"]

    profiles, total = repo.search_profiles(
        me, role=role, commodity=commodity, city=city, q=q,
        user_verified_only=user_verified_only,
        business_verified_only=business_verified_only,
        page=page, limit=limit,
    )
    statuses = repo.bulk_statuses(me, [p.users_id for p in profiles])
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "results": [
            fmt_profile(
                p,
                msg_req_status=statuses.get(p.users_id, {}).get("msg_req_status"),
                follow_status=statuses.get(p.users_id, {}).get("follow_status", False),
            )
            for p in profiles
        ],
    }


def search_suggestions(repo: IConnectionsRepository, q: str) -> list[dict]:
    """
    Quick name / business_name suggestions. Returns top 8.
    (ILIKE match — no pg_trgm extension required.)
    """
    return [fmt_profile(p) for p in repo.suggest_profiles(q, 8)]
