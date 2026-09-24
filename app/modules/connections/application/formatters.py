"""Pure response formatting for connection lists. No database access.

app_new had four byte-identical copies of `_fmt_profile` across the use-case
files; this is the single definition.
"""
from __future__ import annotations


def fmt_profile(profile, *, msg_req_status: str | None = None,
                follow_status: bool = False) -> dict:
    """Serialize a Profile into a flat dict for connection list responses."""
    return {
        "user_id":              str(profile.users_id),
        "name":                 profile.name,
        "avatar_url":           profile.avatar_url,
        "role":                 profile.role.name.lower() if profile.role else None,
        "commodity":            [pc.commodity.name.lower() for pc in profile.commodities],
        "is_user_verified":     profile.is_user_verified,
        "is_business_verified": profile.is_business_verified,
        "quantity_min":         int(profile.quantity_min),
        "quantity_max":         int(profile.quantity_max),
        "business_name":        profile.business.business_name,
        "city":                 profile.business.city,
        "state":                profile.business.state,
        "msg_req_status":       msg_req_status,
        "follow_status":        follow_status,
    }
