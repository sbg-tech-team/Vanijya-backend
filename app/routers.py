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
    from app.modules.chat.presentation.router import router as chat_router
    from app.modules.connections.presentation.router import (
        connections_router, recommendations_router,
    )
    from app.modules.deeplink.presentation.router import router as deeplink_router
    from app.modules.groups.presentation.router import router as groups_router
    from app.modules.news.presentation.router import router as news_router
    from app.modules.onboarding.presentation.router import router as onboarding_router
    from app.modules.post.presentation.router import router as post_router
    from app.modules.post.recommendation.router import router as post_rec_router
    from app.modules.post.recommendation.session_taste.router import (
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
        ("post.interactions", post_interactions_router),
        ("connections", connections_router),
        ("recommendations", recommendations_router),
        ("groups", groups_router),
        ("chat", chat_router),
        ("safety", safety_router),
        ("deeplink", deeplink_router),
    ]
    for _, router in ordered:
        app.include_router(router)
    return [name for name, _ in ordered]
