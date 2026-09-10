"""Safety domain exceptions. Routers map these to HTTP codes."""


class SafetyError(Exception):
    """Base for every safety business-rule violation."""


class BlockSelfError(SafetyError):
    """Actor tried to block themselves. -> 400"""


class AlreadyBlockedError(SafetyError):
    """Block already exists. -> 409"""


class BlockNotFoundError(SafetyError):
    """No such block to remove. -> 404"""


class SelfReportError(SafetyError):
    """Actor tried to report themselves. -> 400"""


class DuplicateReportError(SafetyError):
    """Actor already reported this target. -> 409"""
