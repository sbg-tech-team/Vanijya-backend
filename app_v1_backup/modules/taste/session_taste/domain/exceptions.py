class SessionTasteError(Exception):
    """Base for all session taste failures."""


class SessionWriteError(SessionTasteError):
    """Raised when signals cannot be written to the session store."""


class SessionReadError(SessionTasteError):
    """Raised when session taste cannot be read."""
