from fastapi import APIRouter

router = APIRouter(prefix="/news/recommendations", tags=["News Recommendations"])

# Personalized feed endpoint will live here once mechanisms 2 and 3 are wired in.
# GET /news/recommendations/feed  — ranked personal feed (role + profile + taste scores)
