from fastapi import APIRouter

router = APIRouter(prefix="/news", tags=["News Feed"])

# GET /news/feed/trending                  — velocity_score DESC, cursor-paginated
# GET /news/feed/saved                     — user's saved articles, saved_at DESC
# GET /news/feed/global                    — placeholder (category filter)
# GET /news/feed/government                — placeholder (category filter)
# GET /news/feed/domestic                  — placeholder (category filter)
# GET /news/articles/{article_id}          — full card detail
# GET /news/feed/recommendations           — personalized feed, ranked by recommendation engine