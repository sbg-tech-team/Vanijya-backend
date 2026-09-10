"""Session lifecycle use cases (create, refresh, revoke).

Token generation and expiry rules are ported from
app_old/modules/auth/service.py; all persistence now goes through
IOnboardingRepository.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.core.config import settings
from app.core.security.jwt_handler import create_access_token
from app.modules.onboarding.domain.exceptions import (
    InvalidRefreshTokenError,
    ProfileNotFoundError,
    SessionExpiredError,
)
from app.modules.onboarding.domain.interfaces.repository import IOnboardingRepository

_REFRESH_TOKEN_BYTES = 48


def _hash_token(raw: str) -> str:
    """SHA-256 hex digest — never store the raw refresh token."""
    return hashlib.sha256(raw.encode()).hexdigest()


def create_session(
    repo: IOnboardingRepository,
    user_id: UUID,
    profile_id: int,
    *,
    device_info: str | None = None,
    ip_address: str | None = None,
) -> tuple[str, str]:
    """
    Create a new session row and issue (access_token, refresh_token).

    The refresh token is an opaque random string; only its SHA-256 hash is
    persisted. The access token embeds the session UUID as ``jti`` and
    ``profile_id`` as ``pid`` so callers never need an extra DB lookup.
    """
    session_id = uuid.uuid4()
    raw_refresh = secrets.token_urlsafe(_REFRESH_TOKEN_BYTES)
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )

    repo.add_session(
        session_id=session_id,
        user_id=user_id,
        refresh_token_hash=_hash_token(raw_refresh),
        expires_at=expires_at,
        device_info=device_info,
        ip_address=ip_address,
    )
    return create_access_token(user_id, session_id, profile_id), raw_refresh


def refresh_session(repo: IOnboardingRepository, raw_refresh_token: str) -> tuple[str, str]:
    """
    Validate a refresh token, rotate it, and return a new
    (access_token, refresh_token).

    Raises InvalidRefreshTokenError if the token is unknown or already revoked.
    Raises SessionExpiredError if the session's expiry timestamp has passed.
    Raises ProfileNotFoundError if no profile row exists for the session's user.
    """
    session = repo.get_active_session_by_refresh_hash(_hash_token(raw_refresh_token))
    if session is None:
        raise InvalidRefreshTokenError("Invalid or revoked refresh token.")

    if datetime.now(timezone.utc) > session.expires_at.replace(tzinfo=timezone.utc):
        repo.deactivate_session(session.session_id)
        raise SessionExpiredError("Refresh token has expired. Please sign in again.")

    profile_id = repo.get_profile_id_for_user(session.user_id)
    if profile_id is None:
        raise ProfileNotFoundError("User profile not found.")

    # Rotate: new refresh token + new access token, same session row.
    new_raw_refresh = secrets.token_urlsafe(_REFRESH_TOKEN_BYTES)
    repo.rotate_refresh_token(
        session.session_id, _hash_token(new_raw_refresh), datetime.now(timezone.utc)
    )
    return create_access_token(session.user_id, session.session_id, profile_id), new_raw_refresh


def revoke_session_by_jti(repo: IOnboardingRepository, session_id: UUID) -> None:
    """Deactivate the session identified by the JWT jti (used on logout)."""
    repo.deactivate_session(session_id)


def revoke_all_sessions(repo: IOnboardingRepository, user_id: UUID) -> None:
    """Force-logout: invalidate every active session for a user."""
    repo.deactivate_all_sessions(user_id)
