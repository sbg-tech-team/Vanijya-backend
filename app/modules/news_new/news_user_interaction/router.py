from fastapi import APIRouter

router = APIRouter(prefix="/news", tags=["News Behaviour"])

# POST /news/interactions/batch   — client event batch (impression, dwell, open_article, share_tap)
# POST /news/{id}/like            — toggle like
# POST /news/{id}/save            — toggle save
# POST /news/{id}/share           — record share event
