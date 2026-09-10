from app.modules.connections.db.postgres import AsyncSessionLocal
from sqlalchemy import text
# app/routes/recommendations.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


async def _fetch_user_from_postgres(user_id: int) -> dict:
    """Fetch a user row from Postgres by user_id."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text('SELECT * FROM "Users" WHERE user_id = :uid'),
            {"uid": user_id}
        )
        row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    return dict(row)
