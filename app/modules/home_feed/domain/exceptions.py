"""
Home Feed Domain Exceptions — pure Python, no framework dependencies.

All exceptions inherit from HomeFeedDomainError so callers can catch
the entire domain with a single except clause when needed.
"""
from __future__ import annotations


# ── Base ───────────────────────────────────────────────────────────────────────

class HomeFeedDomainError(Exception):
    """Base class for all home feed domain exceptions."""


# ── Profile / User ─────────────────────────────────────────────────────────────

class ProfileNotFoundError(HomeFeedDomainError):
    """
    Raised when the requesting user's profile cannot be resolved.

    Typically occurs when a valid auth token references a user_id that has no
    associated profile row — e.g. the profile was deleted after token issuance.
    """
    def __init__(self, profile_id: int | None = None, user_id: object = None) -> None:
        if profile_id is not None:
            detail = f"Profile with id={profile_id} not found."
        elif user_id is not None:
            detail = f"No profile found for user_id={user_id}."
        else:
            detail = "Profile not found."
        super().__init__(detail)


# ── Feed / Cursor ──────────────────────────────────────────────────────────────

class InvalidCursorError(HomeFeedDomainError):
    """
    Raised when a feed cursor cannot be decoded or is structurally invalid.

    The presentation layer maps this to HTTP 400.
    """
    def __init__(self, raw: str | None = None) -> None:
        detail = f"Invalid or malformed feed cursor: {raw!r}." if raw else "Invalid feed cursor."
        super().__init__(detail)


class FeedExhaustedError(HomeFeedDomainError):
    """
    Raised when all candidate source pools are empty and no more items can be
    produced for any subsequent page.
    """
    def __init__(self) -> None:
        super().__init__("All feed source pools are exhausted; no more items available.")


# ── Source Pipeline ────────────────────────────────────────────────────────────

class SourcePipelineError(HomeFeedDomainError):
    """
    Raised when a source pipeline (post / news / group / connection) fails to
    return candidates and the failure should surface rather than degrade silently.

    In practice the pipelines currently swallow errors and return []; this
    exception exists for explicit error propagation in future iterations.
    """
    def __init__(self, source: str, reason: str = "") -> None:
        detail = f"Source pipeline '{source}' failed."
        if reason:
            detail += f" Reason: {reason}"
        super().__init__(detail)
        self.source = source


# ── Engagement ────────────────────────────────────────────────────────────────

class InvalidEngagementSignalError(HomeFeedDomainError):
    """
    Raised when an engagement signal contains an unrecognised item_type or
    action that cannot be mapped to a known ActionType enum value.
    """
    def __init__(self, field: str, value: str) -> None:
        super().__init__(
            f"Invalid engagement signal: unrecognised {field}='{value}'."
        )
        self.field = field
        self.value = value


class EmptyEngagementBatchError(HomeFeedDomainError):
    """Raised when a submitted EngagementBatch contains no signals."""
    def __init__(self) -> None:
        super().__init__("Engagement batch must contain at least one signal.")


# ── Session Taste ─────────────────────────────────────────────────────────────

class SessionTasteUnavailableError(HomeFeedDomainError):
    """
    Raised when the Redis session taste store is unreachable and the caller
    requires a live taste value (rather than falling back to page defaults).
    """
    def __init__(self, profile_id: int | None = None) -> None:
        detail = (
            f"Session taste unavailable for profile_id={profile_id}."
            if profile_id is not None
            else "Session taste store is unavailable."
        )
        super().__init__(detail)


# ── Mixer ─────────────────────────────────────────────────────────────────────

class MixerConfigurationError(HomeFeedDomainError):
    """
    Raised when the feed mixer receives an invalid weights dict (e.g. all
    weights zero, unknown content type keys, or negative values).
    """
    def __init__(self, reason: str = "") -> None:
        detail = "Invalid mixer configuration."
        if reason:
            detail += f" {reason}"
        super().__init__(detail)
