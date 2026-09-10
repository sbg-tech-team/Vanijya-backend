"""
Main router for the news module.

Registers all sub-routers under the /news prefix.
Imported by the module's __init__.py and by the app's main router registry
(app/routers.py).
"""
from __future__ import annotations

from fastapi import APIRouter

from app.modules.news.presentation.routes.admin import router as admin_router
from app.modules.news.presentation.routes.feed import router as feed_router
from app.modules.news.presentation.routes.interactions import router as interactions_router

router = APIRouter(prefix="/news")

router.include_router(feed_router)
router.include_router(interactions_router)
router.include_router(admin_router)
