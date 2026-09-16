"""Calling domain exceptions. The router maps these to HTTP codes."""


class CallingError(Exception):
    """Base for every calling business-rule violation."""


class CallNotFoundError(CallingError):
    """No such call, or the caller is not a participant. -> 404"""


class CallTargetNotFoundError(CallingError):
    """Target user or group does not exist. -> 404"""


class SelfCallError(CallingError):
    """Actor tried to call themselves. -> 400"""


class CallBlockedError(CallingError):
    """Either party has blocked the other. -> 403"""


class NotGroupMemberError(CallingError):
    """Actor is not a member of the group being called. -> 403"""


class NotParticipantError(CallingError):
    """Actor is not a participant in this call. -> 403"""


class CallerBusyError(CallingError):
    """Actor already has a ringing or active call. -> 409"""


class CalleeBusyError(CallingError):
    """Target already has a ringing or active call (1:1 only). -> 409"""


class CallNotRingingError(CallingError):
    """Accept/reject attempted on a call that is no longer ringing. -> 409"""


class CallAlreadyEndedError(CallingError):
    """Mutating endpoint hit on a terminal call. -> 409"""


class CallFullError(CallingError):
    """Group call is at MAX_CALL_PARTICIPANTS. -> 409"""


class CallBudgetExceededError(CallingError):
    """Per-user daily or platform monthly participant-minute budget is spent.
    The guardrail against a runaway bill. -> 429"""


class VideoNotAvailableError(CallingError):
    """media="video" requested before video ships. -> 501"""


class VideoProviderError(CallingError):
    """Stream is unreachable or misconfigured. -> 503"""
