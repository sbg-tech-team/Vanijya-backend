"""
Value objects for the onboarding module.

Pure Python — no SQLAlchemy, FastAPI, Pydantic, or Redis imports.
Value objects are immutable (frozen dataclasses) and compared by value,
not by identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AuthOutcome(str, Enum):
    """
    Result of a Firebase token verification attempt.

    NEW_USER        — no DB row exists; caller must complete onboarding.
    INCOMPLETE_USER — user row exists but profile creation was never finished.
    RETURNING_USER  — fully onboarded user; issue a token pair.
    """

    NEW_USER = "new_user"
    INCOMPLETE_USER = "incomplete_user"
    RETURNING_USER = "returning_user"


class TokenType(str, Enum):
    """
    Distinguishes the two short-lived tokens the service may issue.

    ONBOARDING — single-use token granted before a profile exists;
                 carries phone + country_code but no session row.
    ACCESS     — standard bearer token with jti (session id) and pid
                 (profile id) embedded.
    REFRESH    — opaque random string; only its SHA-256 hash is stored.
    """

    ONBOARDING = "onboarding"
    ACCESS = "access"
    REFRESH = "refresh"


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PhoneNumber:
    """
    A validated, normalised phone number split into its constituent parts.

    ``country_code`` includes the leading '+' (e.g. "+91").
    ``number``       contains only the subscriber digits (e.g. "9876543210").
    """

    country_code: str   # e.g. "+91"
    number: str         # digits only, no country-code prefix

    def full(self) -> str:
        """Return the E.164-style concatenation, e.g. '+919876543210'."""
        return f"{self.country_code}{self.number}"

    def __post_init__(self) -> None:
        if not self.country_code.startswith("+"):
            raise ValueError(
                f"country_code must start with '+', got: {self.country_code!r}"
            )
        if not self.number.isdigit():
            raise ValueError(
                f"number must contain only digits, got: {self.number!r}"
            )


@dataclass(frozen=True)
class TokenPair:
    """
    An (access_token, refresh_token) pair returned after a successful login
    or token rotation.
    """

    access_token: str
    refresh_token: str
    expires_in: int  # seconds until access token expires
