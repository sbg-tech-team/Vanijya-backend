class GlobalSessionError(Exception):
    """Base for all global session failures."""


class GlobalSessionWriteError(GlobalSessionError):
    """Raised when the global session cannot be written."""


class GlobalSessionReadError(GlobalSessionError):
    """Raised when the global session cannot be read."""
