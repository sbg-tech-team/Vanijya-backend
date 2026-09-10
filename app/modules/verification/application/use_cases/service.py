"""Aggregate entry point for the verification use cases."""
from app.modules.verification.application.use_cases.get_status import (  # noqa: F401
    get_verification_status,
)
from app.modules.verification.application.use_cases.verify_document import (  # noqa: F401
    CATEGORY_MAP,
    ROLE_KYB_DOC,
    verify_document,
)

__all__ = [
    "verify_document",
    "get_verification_status",
    "CATEGORY_MAP",
    "ROLE_KYB_DOC",
]
