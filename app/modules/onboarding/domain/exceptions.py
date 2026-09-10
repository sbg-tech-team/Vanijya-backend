"""
Domain exceptions for the onboarding module.

Pure Python — no SQLAlchemy, FastAPI, Pydantic, or Redis imports.
Each class maps to a distinct error scenario so callers can handle
them individually without inspecting message strings.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class OnboardingDomainError(Exception):
    """
    Root exception for all onboarding-domain errors.
    Catch this to handle any onboarding error generically.
    """


# ---------------------------------------------------------------------------
# Firebase / token verification
# ---------------------------------------------------------------------------

class InvalidFirebaseTokenError(OnboardingDomainError):
    """
    Raised when a Firebase ID token cannot be verified — it may be
    malformed, expired, or signed with an unknown key.
    """


class MissingPhoneNumberError(OnboardingDomainError):
    """
    Raised when a Firebase token is valid but does not carry a
    ``phone_number`` claim (e.g. the user signed in via email/password
    instead of phone OTP).
    """


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

class SessionNotFoundError(OnboardingDomainError):
    """
    Raised when a refresh or revoke operation cannot locate a matching
    session row — the token may be unknown or already deleted.
    """


class SessionRevokedError(OnboardingDomainError):
    """
    Raised when a session is found but has already been deactivated
    (``is_active = False``), indicating a previously logged-out or
    force-revoked session.
    """


class SessionExpiredError(OnboardingDomainError):
    """
    Raised when a session's ``expires_at`` timestamp is in the past.
    The user must perform a fresh login to obtain new tokens.
    """


class InvalidRefreshTokenError(OnboardingDomainError):
    """
    Raised when the supplied refresh token hash does not match any
    active session.  This is the public-facing variant that intentionally
    does not distinguish between 'not found' and 'wrong hash'.
    """


# ---------------------------------------------------------------------------
# User / profile state
# ---------------------------------------------------------------------------

class UserNotFoundError(OnboardingDomainError):
    """
    Raised when a user record is expected to exist (e.g. during token
    refresh) but cannot be found in the data store.
    """


class ProfileNotFoundError(OnboardingDomainError):
    """
    Raised when a profile linked to an existing user cannot be located —
    typically during refresh when ``profile_id`` must be embedded in the
    new access token.
    """


class UserAlreadyExistsError(OnboardingDomainError):
    """
    Raised when an attempt is made to create a user with a
    (country_code, phone_number) pair that is already registered.
    """


class OnboardingIncompleteError(OnboardingDomainError):
    """
    Raised when a full-access token is requested for a user who has not
    yet finished the onboarding flow (no profile row exists).
    """
