"""
Domain exceptions for the connections module.
Pure Python — no SQLAlchemy, FastAPI, Pydantic, or Redis imports.

Each exception maps to a specific error scenario discovered in service.py.
HTTP status codes are NOT encoded here; the presentation layer is responsible
for translating these exceptions into appropriate HTTP responses.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class ConnectionsDomainError(Exception):
    """Base class for all connections-domain exceptions."""


# ---------------------------------------------------------------------------
# Follow graph errors
# ---------------------------------------------------------------------------

class SelfFollowError(ConnectionsDomainError):
    """Raised when a user attempts to follow themselves."""
    def __init__(self) -> None:
        super().__init__("A user cannot follow themselves.")


class AlreadyFollowingError(ConnectionsDomainError):
    """Raised when a follow edge already exists between the two users."""
    def __init__(self, following_id: object) -> None:
        super().__init__(f"Already following user {following_id}.")
        self.following_id = following_id


class NotFollowingError(ConnectionsDomainError):
    """Raised when trying to unfollow a user that is not currently followed."""
    def __init__(self, following_id: object) -> None:
        super().__init__(f"Not currently following user {following_id}.")
        self.following_id = following_id


# ---------------------------------------------------------------------------
# Message request errors
# ---------------------------------------------------------------------------

class SelfRequestError(ConnectionsDomainError):
    """Raised when a user tries to send a message request to themselves."""
    def __init__(self) -> None:
        super().__init__("Cannot send a message request to yourself.")


class MessageRequestAlreadySentError(ConnectionsDomainError):
    """Raised when an open (pending) message request to the same receiver already exists."""
    def __init__(self, receiver_id: object) -> None:
        super().__init__(f"A message request to user {receiver_id} has already been sent.")
        self.receiver_id = receiver_id


class AlreadyConnectedError(ConnectionsDomainError):
    """Raised when a message request is sent but the two users are already connected
    (i.e., a previously accepted request exists)."""
    def __init__(self, receiver_id: object) -> None:
        super().__init__(f"Already connected with user {receiver_id}.")
        self.receiver_id = receiver_id


class MessageRequestNotFoundError(ConnectionsDomainError):
    """Raised when the requested MessageRequest row does not exist, has already been
    acted on, or the caller is not the intended receiver."""
    def __init__(self, request_id: object) -> None:
        super().__init__(
            f"Message request {request_id} not found, already acted on, "
            "or you are not the receiver."
        )
        self.request_id = request_id


class NoPendingRequestError(ConnectionsDomainError):
    """Raised when trying to withdraw a request that is not in pending/declined state."""
    def __init__(self, receiver_id: object) -> None:
        super().__init__(
            f"No pending or declined request to user {receiver_id} found to withdraw."
        )
        self.receiver_id = receiver_id


# ---------------------------------------------------------------------------
# Conversation / DM errors
# ---------------------------------------------------------------------------

class ConversationBlockedError(ConnectionsDomainError):
    """Raised when accepting a message request would reactivate a blocked conversation."""
    def __init__(self) -> None:
        super().__init__("This conversation is blocked and cannot be reactivated.")


# ---------------------------------------------------------------------------
# Profile / recommendation errors
# ---------------------------------------------------------------------------

class ProfileNotFoundError(ConnectionsDomainError):
    """Raised when a user profile does not exist (e.g., onboarding not completed)."""
    def __init__(self, user_id: object) -> None:
        super().__init__(
            f"Profile for user {user_id} not found — complete onboarding first."
        )
        self.user_id = user_id


class InvalidSearchQueryError(ConnectionsDomainError):
    """Raised when a search query cannot be parsed or contains invalid parameters."""
    def __init__(self, detail: str = "Invalid search query.") -> None:
        super().__init__(detail)
