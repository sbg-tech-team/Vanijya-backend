class TranslationError(Exception):
    """Base class for translation module errors."""


class MessageNotFoundError(TranslationError):
    pass


class ContinuousNotAllowedError(TranslationError):
    """Raised when continuous mode is requested for a group — DMs only."""
    pass


class TranslationEngineUnavailableError(TranslationError):
    """The engine has no API key configured. -> 503, never a raw 500."""
    pass


class NotAConversationMemberError(TranslationError):
    """Reader is not in the DM/group the message belongs to. -> 403.

    Without this, any authenticated user could read the plaintext of any
    message on the platform by POSTing its id to /translate.
    """
    pass
