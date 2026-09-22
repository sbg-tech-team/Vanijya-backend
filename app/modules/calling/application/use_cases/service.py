"""Aggregate entry point for the calling use cases.

Mirrors the shim every other module exposes, so callers can do
`from app.modules.calling.application.use_cases import service` and reach
everything from one place.
"""
from app.modules.calling.application.use_cases.end_call import end_call  # noqa: F401
from app.modules.calling.application.use_cases.get_calls import (  # noqa: F401
    get_call,
    list_calls,
    refresh_token,
)
from app.modules.calling.application.use_cases.heartbeat import heartbeat  # noqa: F401
from app.modules.calling.application.use_cases.initiate_call import (  # noqa: F401
    initiate_call,
)
from app.modules.calling.application.use_cases.register_device import (  # noqa: F401
    register_device,
)
from app.modules.calling.application.use_cases.unregister_device import (  # noqa: F401
    unregister_device,
)
from app.modules.calling.application.use_cases.respond_to_call import (  # noqa: F401
    accept_call,
    reject_call,
)

__all__ = [
    "initiate_call",
    "accept_call",
    "reject_call",
    "end_call",
    "heartbeat",
    "get_call",
    "list_calls",
    "refresh_token",
    "register_device",
    "unregister_device",
]
