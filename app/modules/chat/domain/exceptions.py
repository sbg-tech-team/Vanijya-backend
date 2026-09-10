# exceptions.py — domain-level exceptions for the chat module.
# Pure Python only: no SQLAlchemy, no FastAPI, no Pydantic, no Redis.
# One class per distinct error scenario so callers can catch precisely.


# ── Conversation exceptions ────────────────────────────────────────────────────

class ConversationNotFoundError(Exception):
    """Raised when a conversation ID does not exist or is not accessible to the caller."""


class ConversationAlreadyExistsError(Exception):
    """Raised when attempting to open a DM with a user you already have a conversation with."""


class ConversationAccessDeniedError(Exception):
    """Raised when a user tries to read or write to a conversation they are not a member of."""


class ConversationBlockedError(Exception):
    """Raised when a message send is attempted on a conversation that has been blocked."""


# ── Message exceptions ─────────────────────────────────────────────────────────

class MessageNotFoundError(Exception):
    """Raised when a message ID does not exist."""


class MessageDeleteNotAllowedError(Exception):
    """Raised when a user tries to delete a message they did not send."""


class MessageAlreadyDeletedError(Exception):
    """Raised when an operation is attempted on a message that has already been soft-deleted."""


# ── Member exceptions ─────────────────────────────────────────────────────────

class MemberNotFoundError(Exception):
    """Raised when a user is not a member of the conversation or group being queried."""


class MemberAlreadyExistsError(Exception):
    """Raised when trying to add a user who is already a member of the conversation."""


# ── Media / storage exceptions ─────────────────────────────────────────────────

class ChatMediaUploadError(Exception):
    """Raised when the requested content-type is not allowed for chat media uploads."""


class ChatStorageUnavailableError(Exception):
    """Raised when the underlying object-storage service cannot be reached."""


class ChatMediaNotFoundError(Exception):
    """Raised when a referenced media URL or storage path does not exist."""


# ── Deal exceptions ────────────────────────────────────────────────────────────

class PersonalDealNotFoundError(Exception):
    """Raised when a personal deal referenced in a message does not exist."""


class DealAccessDeniedError(Exception):
    """Raised when a user tries to attach a deal they do not own."""


# ── Permission / policy exceptions ────────────────────────────────────────────

class ChatPermissionDeniedError(Exception):
    """Generic permission denial — caller is not allowed to perform the requested chat action."""


class GroupChatSendNotAllowedError(Exception):
    """Raised when a group member without send permission tries to post a message."""
