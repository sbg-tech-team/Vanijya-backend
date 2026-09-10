"""Verification module public API."""
from app.modules.verification.application.use_cases.service import (  # noqa: F401
    get_verification_status,
    verify_document,
)
from app.modules.verification.domain.exceptions import (  # noqa: F401
    DocumentRejectedError,
    InvalidKybDocumentError,
    KycRequiredError,
    ProfileNotFoundError,
    VerificationError,
)

__all__ = [
    "router",
    "verify_document",
    "get_verification_status",
    "VerificationError",
    "KycRequiredError",
    "InvalidKybDocumentError",
    "ProfileNotFoundError",
    "DocumentRejectedError",
]


# `router` is exported lazily (PEP 562). Importing it eagerly here would mean that
# any `from app.modules.verification.data.models import ...` elsewhere pulls in the whole
# presentation layer, which is how the profile <-> onboarding <-> post import
# cycles arose. `from app.modules.verification import router` still works.
def __getattr__(name):
    if name == "router":
        from app.modules.verification.presentation.router import router as _r
        return _r
    raise AttributeError(f"module {{__name__!r}} has no attribute {{name!r}}")
