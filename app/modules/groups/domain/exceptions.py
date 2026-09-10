"""
Domain exceptions for the Groups module.
Pure Python — no SQLAlchemy, FastAPI, Pydantic, or Redis imports.

Each exception maps to a distinct error scenario surfaced by the service layer.
The presentation layer (router) translates these into HTTP status codes.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class GroupsDomainError(Exception):
    """Root exception for all Groups domain errors."""


# ---------------------------------------------------------------------------
# Not-found errors  (→ HTTP 404)
# ---------------------------------------------------------------------------

class GroupNotFoundError(GroupsDomainError):
    """Raised when a requested group does not exist."""


class GroupMemberNotFoundError(GroupsDomainError):
    """Raised when a user is not a member of a group but membership is required."""


class GroupDealNotFoundError(GroupsDomainError):
    """Raised when a requested group deal does not exist."""


class GroupMediaNotFoundError(GroupsDomainError):
    """Raised when a requested group media item does not exist."""


class GroupJoinRequestNotFoundError(GroupsDomainError):
    """Raised when a referenced join request does not exist."""


class GroupProfileNotFoundError(GroupsDomainError):
    """Raised when the user's profile cannot be found (onboarding incomplete)."""


# ---------------------------------------------------------------------------
# Conflict / duplicate errors  (→ HTTP 409)
# ---------------------------------------------------------------------------

class GroupAlreadyMemberError(GroupsDomainError):
    """Raised when a user attempts to join a group they already belong to."""


class GroupJoinRequestAlreadyPendingError(GroupsDomainError):
    """Raised when a join request already exists and is still pending."""


class GroupJoinRequestAlreadyResolvedError(GroupsDomainError):
    """Raised when an admin tries to resolve a request that was already approved or rejected."""


class GroupDealAlreadyPublishedError(GroupsDomainError):
    """Raised when a deal has already been promoted to the public feed."""


# ---------------------------------------------------------------------------
# Permission / authorisation errors  (→ HTTP 403)
# ---------------------------------------------------------------------------

class GroupPermissionError(GroupsDomainError):
    """Raised when the caller lacks the required role or membership to perform an action."""


class GroupAdminRequiredError(GroupPermissionError):
    """Raised when the operation requires admin role but the caller is only a member."""


class GroupMemberRequiredError(GroupPermissionError):
    """Raised when the operation requires group membership but the caller is not a member."""


class GroupInviteOnlyError(GroupPermissionError):
    """Raised when a user tries to join an invite-only group without an invite link."""


class GroupMemberFrozenError(GroupPermissionError):
    """Raised when a frozen member attempts to post or perform member-only actions."""


class GroupSoleAdminLeaveError(GroupPermissionError):
    """Raised when the sole admin of a group attempts to leave without assigning a successor."""


class GroupDealEditForbiddenError(GroupPermissionError):
    """Raised when someone other than the deal author tries to edit or close it."""


class GroupMediaDeleteForbiddenError(GroupPermissionError):
    """Raised when neither admin nor uploader tries to delete a media item."""


# ---------------------------------------------------------------------------
# Validation errors  (→ HTTP 422)
# ---------------------------------------------------------------------------

class GroupValidationError(GroupsDomainError):
    """Raised when input data violates a domain business rule."""


class GroupUnsupportedMediaTypeError(GroupValidationError):
    """Raised when a media upload uses a content-type not supported by the group media bucket."""


class GroupBusinessProfileMissingError(GroupValidationError):
    """Raised when suggestions are requested but the user's business profile is incomplete."""


# ---------------------------------------------------------------------------
# Storage / infrastructure errors  (→ HTTP 503)
# ---------------------------------------------------------------------------

class GroupStorageError(GroupsDomainError):
    """Raised when an interaction with the object-storage backend fails."""
