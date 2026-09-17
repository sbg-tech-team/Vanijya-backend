"""Single place that knows every router and the order they must be registered in.

main.py should call:

    from app.routers import register_routers
    register_routers(app)

instead of listing routers itself.

Routers are imported lazily inside the function so importing this module does
not drag in the whole presentation layer.
"""
from __future__ import annotations


def register_routers(app) -> list[str]:
    """Register every router on `app`, in the required order. Returns their names."""
    from app.modules.calling.presentation.router import router as calling_router
    from app.modules.chat.presentation.router import router as chat_router
    from app.modules.connections.presentation.router import (
        connections_router, recommendations_router,
    )
    from app.modules.deeplink.presentation.router import router as deeplink_router
    from app.modules.groups.presentation.router import router as groups_router
    from app.modules.news.presentation.router import router as news_router
    from app.modules.onboarding.presentation.router import router as onboarding_router
    from app.modules.post.presentation.router import router as post_router
    from app.modules.post.presentation.recommendation_router import (
        jobs_router as post_rec_jobs_router,
        router as post_rec_router,
    )
    from app.modules.post.presentation.taste_router import (
        jobs_router as post_interaction_jobs_router,
        router as post_interactions_router,
    )
    from app.modules.profile.presentation.router import router as profile_router
    from app.modules.safety.presentation.router import router as safety_router
    from app.modules.verification.presentation.router import router as verification_router

    ordered = [
        ("news", news_router),
        # ── everything else ─────────────────────────────────────────────────
        ("onboarding", onboarding_router),
        ("profile", profile_router),
        ("verification", verification_router),
        ("post", post_router),
        ("post.recommendation", post_rec_router),
        ("post.recommendation.jobs", post_rec_jobs_router),
        ("post.interactions", post_interactions_router),
        ("post.interactions.jobs", post_interaction_jobs_router),
        ("connections", connections_router),
        ("recommendations", recommendations_router),
        ("groups", groups_router),
        ("chat", chat_router),
        ("calling", calling_router),
        ("safety", safety_router),
        ("deeplink", deeplink_router),
    ]
    for _, router in ordered:
        app.include_router(router)

    _register_exception_handlers(app)
    return [name for name, _ in ordered]


def _register_exception_handlers(app) -> None:
    """Map domain and database exceptions to HTTP codes.

    The chat router catches nothing itself, so without this every business rule
    — not a member, blocked conversation, message already gone — surfaces as a
    500. Registered app-wide so new exception types are covered automatically.
    """
    import logging

    from fastapi.responses import JSONResponse
    from sqlalchemy.exc import IntegrityError

    from app.modules.chat.domain.exceptions import ChatError
    from app.modules.chat.presentation.router import chat_exception_status

    log = logging.getLogger(__name__)

    @app.exception_handler(IntegrityError)
    async def _integrity_error(_request, exc: IntegrityError):
        """A constraint violation is the client naming something that is not
        there, or already is. Both were surfacing as 500.

        Any id in a URL can be made up, so `POST /connections/follow/<random>`
        and a dozen like it answered 500 to a perfectly ordinary mistake. The
        handler lives here rather than in each endpoint because the trap is the
        same everywhere: the row reaches the insert before anything checks it.
        """
        name = type(getattr(exc, "orig", None)).__name__
        if name == "ForeignKeyViolation":
            return JSONResponse(status_code=404,
                                content={"detail": "Referenced record not found"})
        if name == "UniqueViolation":
            return JSONResponse(status_code=409,
                                content={"detail": "Already exists"})
        # Anything else is a real defect — a NOT NULL or CHECK we did not guard.
        log.exception("unhandled integrity error")
        return JSONResponse(status_code=400,
                            content={"detail": "Request violates a data constraint"})

    @app.exception_handler(ChatError)
    async def _chat_error(_request, exc: ChatError):
        return JSONResponse(
            status_code=chat_exception_status(exc),
            content={"detail": str(exc) or "Chat error"},
        )
