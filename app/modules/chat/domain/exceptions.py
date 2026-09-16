# exceptions.py — domain-level exceptions for the chat module.
# Pure Python only: no SQLAlchemy, no FastAPI, no Pydantic, no Redis.
# One class per distinct error scenario so callers can catch precisely.


# ── Conversation exceptions ────────────────────────────────────────────────────

class ChatError(Exception):
    """Base for every chat business-rule violation. The app-level handler maps
    subclasses to HTTP codes, so a new one never silently becomes a 500."""

class ConversationNotFoundError(ChatError):
    """Raised when a conversation ID does not exist or is not accessible to the caller."""


class ConversationAlreadyExistsError(ChatError):
    """Raised when attempting to open a DM with a user you already have a conversation with."""


class ConversationAccessDeniedError(ChatError):
    """Raised when a user tries to read or write to a conversation they are not a member of."""


class ConversationBlockedError(ChatError):
    """Raised when a message send is attempted on a conversation that has been blocked."""


# ── Message exceptions ─────────────────────────────────────────────────────────

class MessageNotFoundError(ChatError):
    """Raised when a message ID does not exist."""


class MessageDeleteNotAllowedError(ChatError):
    """Raised when a user tries to delete a message they did not send."""


class MessageAlreadyDeletedError(ChatError):
    """Raised when an operation is attempted on a message that has already been soft-deleted."""


# ── Member exceptions ─────────────────────────────────────────────────────────

class MemberNotFoundError(ChatError):
    """Raised when a user is not a member of the conversation or group being queried."""


class MemberAlreadyExistsError(ChatError):
    """Raised when trying to add a user who is already a member of the conversation."""


# ── Media / storage exceptions ─────────────────────────────────────────────────

class ChatMediaUploadError(ChatError):
    """Raised when the requested content-type is not allowed for chat media uploads."""


class ChatStorageUnavailableError(ChatError):
    """Raised when the underlying object-storage service cannot be reached."""


class ChatMediaNotFoundError(ChatError):
    """Raised when a referenced media URL or storage path does not exist."""


# ── Deal exceptions ────────────────────────────────────────────────────────────

class PersonalDealNotFoundError(ChatError):
    """Raised when a personal deal referenced in a message does not exist."""


class DealAccessDeniedError(ChatError):
    """Raised when a user tries to attach a deal they do not own."""


# ── Permission / policy exceptions ────────────────────────────────────────────

class ChatPermissionDeniedError(ChatError):
    """Generic permission denial — caller is not allowed to perform the requested chat action."""


class GroupChatSendNotAllowedError(ChatError):
    """Raised when a group member without send permission tries to post a message."""
