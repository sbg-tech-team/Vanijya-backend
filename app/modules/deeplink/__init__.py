"""Deeplink module public API."""
from app.modules.deeplink.application.use_cases.service import (  # noqa: F401
    get_news_share_link,
    get_post_share_link,
    get_user_share_link,
)
from app.modules.deeplink.domain.exceptions import (  # noqa: F401
    DeepLinkError,
    DeepLinkNotFoundError,
)

__all__ = [
    "router",
    "get_post_share_link",
    "get_news_share_link",
    "get_user_share_link",
    "DeepLinkError",
    "DeepLinkNotFoundError",
]


# `router` is exported lazily (PEP 562). Importing it eagerly here would mean that
# any `from app.modules.deeplink.data.models import ...` elsewhere pulls in the whole
# presentation layer, which is how the profile <-> onboarding <-> post import
# cycles arose. `from app.modules.deeplink import router` still works.
def __getattr__(name):
    if name == "router":
        from app.modules.deeplink.presentation.router import router as _r
        return _r
    raise AttributeError(f"module {{__name__!r}} has no attribute {{name!r}}")
