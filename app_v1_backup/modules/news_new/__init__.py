from fastapi import APIRouter

from .ingestion.router import router as ingestion_router
from .news_user_interaction.router import router as behaviour_router
from .news_recommendation_engine.router import router as recommendation_router
from .feed.router import router as feed_router

router = APIRouter()
router.include_router(ingestion_router)
router.include_router(behaviour_router)
router.include_router(recommendation_router)
router.include_router(feed_router)
