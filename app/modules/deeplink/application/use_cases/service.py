"""Aggregate entry point for the deeplink use cases."""
from app.modules.deeplink.application.use_cases.build_share_link import (  # noqa: F401
    APP_SCHEME,
    PLAY_STORE_URL,
    get_news_share_link,
    get_post_share_link,
    get_user_share_link,
)
from app.modules.deeplink.domain.exceptions import (  # noqa: F401
    DeepLinkError,
    DeepLinkNotFoundError,
)

__all__ = [
    "get_post_share_link",
    "get_news_share_link",
    "get_user_share_link",
    "DeepLinkError",
    "DeepLinkNotFoundError",
    "APP_SCHEME",
    "PLAY_STORE_URL",
]
