"""
Domain exceptions for the profile module.
Pure Python — no SQLAlchemy, FastAPI, Pydantic, or Redis imports.

Each class maps to one specific error scenario raised inside service.py
so that presentation and application layers can catch them precisely.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class ProfileDomainError(Exception):
    """Base class for all profile domain exceptions."""


# ---------------------------------------------------------------------------
# Not Found
# ---------------------------------------------------------------------------

class ProfileNotFoundError(ProfileDomainError):
    """Raised when a Profile row does not exist for the given identifier."""


class UserNotFoundError(ProfileDomainError):
    """Raised when a User row does not exist for the given identifier."""


class BusinessNotFoundError(ProfileDomainError):
    """Raised when a Business row does not exist for the given profile."""


# ---------------------------------------------------------------------------
# Conflict / Already Exists
# ---------------------------------------------------------------------------

class ProfileConflictError(ProfileDomainError):
    """Raised when a Profile already exists for a user (duplicate create)."""


class UserConflictError(ProfileDomainError):
    """Raised when a User with the same phone number already exists."""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class ProfileValidationError(ProfileDomainError):
    """
    Raised when domain invariants are violated, e.g.:
    - quantity_min > quantity_max
    - invalid role_id / commodity_id / interest_id
    - unsupported avatar content type
    - avatar URL does not belong to this profile
    """


class InvalidRoleError(ProfileValidationError):
    """Raised when an unrecognised role_id is supplied."""


class InvalidCommodityError(ProfileValidationError):
    """Raised when one or more commodity IDs are not found in the lookup table."""


class InvalidInterestError(ProfileValidationError):
    """Raised when one or more interest IDs are not found in the lookup table."""


class InvalidQuantityRangeError(ProfileValidationError):
    """Raised when quantity_min > quantity_max."""


class InvalidAvatarContentTypeError(ProfileValidationError):
    """Raised when the uploaded avatar MIME type is not allowed."""


class AvatarOwnershipError(ProfileValidationError):
    """Raised when the avatar URL does not belong to the requesting profile."""


class AvatarNotUploadedError(ProfileValidationError):
    """Raised when the avatar file is not present in storage at save time."""


# ---------------------------------------------------------------------------
# Infrastructure / external service errors
# ---------------------------------------------------------------------------

class ProfileStorageUnavailableError(ProfileDomainError):
    """
    Raised when the storage backend (e.g. Supabase) is temporarily unreachable
    and avatar existence cannot be verified.
    """


class EmbeddingBuildError(ProfileDomainError):
    """Raised when the IS/post-feed vector cannot be built for a profile."""
