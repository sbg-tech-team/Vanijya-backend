from app.modules.onboarding.application.use_cases.service import (
    create_session,
    refresh_session,
    revoke_session_by_jti,
    revoke_all_sessions,
    verify_firebase_token,
    issue_onboarding_token,
)
from app.modules.onboarding.data.models import UserSession

__all__ = [
    "router",
    "create_session",
    "refresh_session",
    "revoke_session_by_jti",
    "revoke_all_sessions",
    "verify_firebase_token",
    "issue_onboarding_token",
    "UserSession",
]


# `router` is exported lazily (PEP 562). Importing it eagerly here would mean that
# any `from app.modules.onboarding.data.models import ...` elsewhere pulls in the whole
# presentation layer, which is how the profile <-> onboarding <-> post import
# cycles arose. `from app.modules.onboarding import router` still works.
def __getattr__(name):
    if name == "router":
        from app.modules.onboarding.presentation.router import router as _r
        return _r
    raise AttributeError(f"module {{__name__!r}} has no attribute {{name!r}}")
