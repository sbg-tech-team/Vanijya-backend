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


class LanguageNotChosenError(TranslationError):
    """App language is English and the reader never picked a translation
    language — nothing to translate into. The client prompts the reader to
    choose one (PUT /translate/preference) rather than the server guessing."""
    pass


class TranslationRejectedError(TranslationError):
    """The engine's output failed a quality check (wrong script, a word
    mixing scripts, a number lost or changed) twice in a row. Nothing was
    stored. Single tap -> 502; continuous mode simply leaves the original."""
    pass
