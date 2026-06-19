from fastapi import APIRouter

router = APIRouter(prefix="/news/admin", tags=["News Ingestion"])

# Admin/internal endpoints — populated when ingestion pipeline is built
