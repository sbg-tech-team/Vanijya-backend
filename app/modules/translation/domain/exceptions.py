class TranslationError(Exception):
    """Base class for translation module errors."""


class MessageNotFoundError(TranslationError):
    pass


class ContinuousNotAllowedError(TranslationError):
    """Raised when continuous mode is requested for a group — DMs only."""
    pass
