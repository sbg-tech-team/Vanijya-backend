# app/db/pgvector.py
from sqlalchemy import text
from fastapi import HTTPException
from app.modules.connections.db.postgres import AsyncSessionLocal


def list_to_pgvec(vec: list[float]) -> str:
    """Convert a Python float list to a PostgreSQL vector literal: '[0.1,0.2,...]'"""
    return "[" + ",".join(str(v) for v in vec) + "]"


async def fetch_user(user_id: int) -> dict:
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


async def vector_search(query_vec: list[float], exclude_user_id: int, top_k: int) -> list[dict]:
    """
    Cosine ANN search via pgvector HNSW index.
    Returns up to top_k rows ordered by cosine similarity descending.
    """
    vec_str = list_to_pgvec(query_vec)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text("""
                SELECT
                    user_id, role, commodity, city, state,
                    min_quantity_mt, max_quantity_mt,
                    1 - (embedding <=> CAST(:vec AS vector)) AS similarity
                FROM "Users"
                WHERE user_id != :exclude_id
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:vec AS vector)
                LIMIT :k
            """),
            {"vec": vec_str, "exclude_id": exclude_user_id, "k": top_k}
        )
        rows = result.mappings().all()
    return [dict(r) for r in rows]


async def update_embedding(user_id: int, vec: list[float]) -> None:
    """Re-write the embedding column for a single user (used by /refresh)."""
    vec_str = list_to_pgvec(vec)
    async with AsyncSessionLocal() as db:
        await db.execute(
            text('UPDATE "Users" SET embedding = CAST(:vec AS vector) WHERE user_id = :uid'),
            {"vec": vec_str, "uid": user_id}
        )
        await db.commit()
