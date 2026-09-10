"""Safety module public API. Other modules import from here, not from internals."""
from app.modules.safety.application.use_cases.service import (  # noqa: F401
    block_status,
    block_user,
    either_blocked,
    is_blocked,
    list_blocked,
    list_my_reports,
    submit_report,
    unblock_user,
)
from app.modules.safety.domain.exceptions import (  # noqa: F401
    AlreadyBlockedError,
    BlockNotFoundError,
    BlockSelfError,
    DuplicateReportError,
    SafetyError,
    SelfReportError,
)

__all__ = [
    "router",
    "block_user",
    "unblock_user",
    "list_blocked",
    "block_status",
    "is_blocked",
    "either_blocked",
    "submit_report",
    "list_my_reports",
    "SafetyError",
    "BlockSelfError",
    "AlreadyBlockedError",
    "BlockNotFoundError",
    "SelfReportError",
    "DuplicateReportError",
]


# `router` is exported lazily (PEP 562). Importing it eagerly here would mean that
# any `from app.modules.safety.data.models import ...` elsewhere pulls in the whole
# presentation layer, which is how the profile <-> onboarding <-> post import
# cycles arose. `from app.modules.safety import router` still works.
def __getattr__(name):
    if name == "router":
        from app.modules.safety.presentation.router import router as _r
        return _r
    raise AttributeError(f"module {{__name__!r}} has no attribute {{name!r}}")
