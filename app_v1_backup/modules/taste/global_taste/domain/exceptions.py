class GlobalTasteError(Exception):
    """Base for all global taste failures."""


class GlobalTasteWriteError(GlobalTasteError):
    """Raised when a promotion delta cannot be persisted."""


class GlobalTasteReadError(GlobalTasteError):
    """Raised when global taste weights cannot be read."""
