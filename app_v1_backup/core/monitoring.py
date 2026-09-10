"""Sentry initialization — error tracking + performance tracing.

Auto-instruments FastAPI (request transactions), SQLAlchemy (db.query spans),
httpx (http.client spans for Gemini/GNews/Groq/Firebase), and Redis.
Call init_sentry() once at process startup, before the FastAPI app is built.
No-op when SENTRY_DSN is unset, so local dev without a DSN is unaffected.
"""

import logging

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sentry_sdk.integrations.httpx import HttpxIntegration
from sentry_sdk.integrations.redis import RedisIntegration
from sentry_sdk.integrations.logging import LoggingIntegration

from app.core.config import settings

logger = logging.getLogger(__name__)


def init_sentry() -> None:
    if not settings.SENTRY_DSN:
        logger.info("Sentry disabled (SENTRY_DSN not set).")
        return

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        # Performance: capture full request transactions with span breakdowns.
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        # Profiling: function-level timing inside each traced transaction.
        profiles_sample_rate=settings.SENTRY_PROFILES_SAMPLE_RATE,
        # Attach request bodies so slow/failed endpoints show their payload.
        send_default_pii=True,
        integrations=[
            StarletteIntegration(),
            FastApiIntegration(),
            SqlalchemyIntegration(),
            HttpxIntegration(),
            RedisIntegration(),
            # Send logging.error(...) and above to Sentry as events; INFO as breadcrumbs.
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
    )
    logger.info("Sentry initialized (env=%s).", settings.ENVIRONMENT)


# Ordered longest-prefix-first so /news/admin wins over /news, etc.
_MODULE_PREFIXES = [
    ("/api/v1/groups", "groups"),
    ("/news/admin", "news-ingestion"),
    ("/news", "news"),
    ("/connections", "connections"),
    ("/recommendations", "connections"),
    ("/feed", "home-feed"),
    ("/safety", "safety"),
    ("/chat", "chat"),
    ("/auth", "auth"),
    ("/profile", "profile"),
    ("/post", "post"),
    ("/verification", "verification"),
    ("/deeplink", "deeplink"),
]


def module_for_path(path: str) -> str | None:
    for prefix, module in _MODULE_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return module
    return None


def install_module_tag_middleware(app) -> None:
    """Tag every request's Sentry transaction with its owning module.

    Lets you filter/group transactions by `module` in Sentry instead of
    matching URL prefixes by hand. No-op when Sentry is disabled.
    """
    if not settings.SENTRY_DSN:
        return

    @app.middleware("http")
    async def _tag_module(request, call_next):
        module = module_for_path(request.url.path)
        if module:
            sentry_sdk.set_tag("module", module)
        return await call_next(request)
