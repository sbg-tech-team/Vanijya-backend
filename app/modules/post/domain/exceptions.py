"""Domain exceptions for the post module.

All exceptions are pure Python — no framework dependencies.
"""


class PostNotFoundError(Exception):
    """Raised when a requested post does not exist or belongs to a deleted profile."""


class PostForbiddenError(Exception):
    """Raised when the caller does not own the post or the operation is not allowed."""


class CommentNotFoundError(Exception):
    """Raised when a requested comment does not exist on the given post."""


class CommentForbiddenError(Exception):
    """Raised when the caller tries to delete another user's comment."""


class CommentsDisabledError(Exception):
    """Raised when a comment is attempted on a post that has comments disabled."""


class PostImageUploadError(Exception):
    """Raised for invalid content-type, wrong storage bucket, or unconfirmed upload."""


class PostStorageUnavailableError(Exception):
    """Raised when object-storage verification is temporarily unavailable."""


class DealDetailsRequiredError(Exception):
    """Raised when a Deal/Requirement post is created without deal_details."""


class InvalidPostCategoryError(Exception):
    """Raised when an operation is attempted on a post category that does not support it."""


class ProfileNotFoundError(Exception):
    """No profile behind the authenticated user. -> 404.

    Distinct from ValueError so an internal ValueError (a bad unpack, a bad
    cast) surfaces as a 500 and reaches Sentry, instead of being reported to
    the client as "not found" with the raw Python message attached.
    """
