# app/routes/recommendations.py
from fastapi import APIRouter
from pydantic import BaseModel
from app.modules.connections.db.pgvector import fetch_user, vector_search, update_embedding
from app.modules.connections.encoding.vector import build_query_vector, build_candidate_vector
# ── OLD ChromaDB imports (removed) ──
# import time
# from app.db.postgres import AsyncSessionLocal
# from app.db.chromadb import get_chroma_collection
# from sqlalchemy import text

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

TOP_K = 20

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _fmt_matches(rows: list[dict]) -> list[dict]:
    """Shape pgvector result rows into the public response format."""
    return [
        {
            "user_id":   r["user_id"],
            "role":      r["role"],
            "commodity": r["commodity"],
            "city":      r["city"],
            "state":     r["state"],
            "qty_range": f"{r['min_quantity_mt']}–{r['max_quantity_mt']}mt",
            "similarity":round(float(r["similarity"]), 4),
        }
        for r in rows
    ]

# ── OLD ChromaDB helpers (kept for reference) ──────────────────────────────
# async def _fetch_user_from_postgres(user_id: int) -> dict:
#     async with AsyncSessionLocal() as db:
#         result = await db.execute(text('SELECT * FROM "Users" WHERE user_id = :uid'), {"uid": user_id})
#         row = result.mappings().first()
#     if not row:
#         raise HTTPException(status_code=404, detail=f"User {user_id} not found")
#     return dict(row)

# async def _fetch_user_from_chromadb(user_id: int) -> dict:
#     collection = get_chroma_collection()
#     result = collection.get(ids=[str(user_id)], include=["metadatas"])
#     if not result["ids"]:
#         raise HTTPException(status_code=404, detail=f"User {user_id} not found")
#     return result["metadatas"][0]

# def _run_search(query_vec, exclude_user_id, top_k) -> list[dict]:
#     collection = get_chroma_collection()
#     results = collection.query(query_embeddings=[query_vec], n_results=top_k + 1, include=["metadatas", "distances"])
#     matches = []
#     for meta, dist in zip(results["metadatas"][0], results["distances"][0]):
#         if meta["user_id"] == exclude_user_id:
#             continue
#         matches.append({"user_id": meta["user_id"], "role": meta["role"], "commodity": meta["commodity"],
#                         "city": meta["city"], "state": meta["state"],
#                         "qty_range": f"{meta['qty_min']}–{meta['qty_max']}mt", "similarity": round(1 - dist, 4)})
#     return matches[:top_k]


# ─── GET /recommendations/{user_id} ──────────────────────────────────────────

@router.get("/{user_id}")
async def get_recommendations(user_id: int):
    """Fetch top 20 matches for a user via pgvector HNSW cosine search."""
    user = await fetch_user(user_id)

    commodity_list = [c.strip() for c in user["commodity"].split(";")]
    query_vec = build_query_vector(
        commodity_list=commodity_list,
        role=user["role"],
        lat=float(user["latitude_raw"]),
        lon=float(user["longitude_raw"]),
        qty_min=int(user["min_quantity_mt"]),
        qty_max=int(user["max_quantity_mt"]),
    )

    matches = await vector_search(query_vec, exclude_user_id=user_id, top_k=TOP_K)

    return {
        "user_id":   user_id,
        "role":      user["role"],
        "commodity": user["commodity"],
        "qty_range": f"{user['min_quantity_mt']}–{user['max_quantity_mt']}mt",
        "total":     len(matches),
        "results":   _fmt_matches(matches),
    }

'''This is the function to calculate which entitiy is taking more time in the recommendation process. We can use this to optimize the code in future.'''

# @router.get("/{user_id}")
# async def get_recommendations(user_id: int):
#     t0 = time.perf_counter()

#     user = await _fetch_user(user_id)
#     t1 = time.perf_counter()
#     print(f"Postgres fetch     : {t1-t0:.3f}s")

#     commodity_list = [c.strip() for c in user["commodity"].split(";")]
#     query_vec = build_query_vector(
#         commodity_list=commodity_list,
#         role=user["role"],
#         lat=float(user["latitude_raw"]),
#         lon=float(user["longitude_raw"]),
#     )
#     t2 = time.perf_counter()
#     print(f"Vector build       : {t2-t1:.3f}s")

#     matches = _run_search(query_vec, exclude_user_id=user_id, top_k=TOP_K)
#     t3 = time.perf_counter()
#     print(f"ChromaDB search    : {t3-t2:.3f}s")

#     print(f"TOTAL              : {t3-t0:.3f}s")

#     return {
#         "user_id":   user_id,
#         "role":      user["role"],
#         "commodity": user["commodity"],
#         "total":     len(matches),
#         "results":   matches,
#     }

# ─── POST /recommendations/search ────────────────────────────────────────────

class SearchPayload(BaseModel):
    commodity:       list[str]   # e.g. ["rice", "cotton"]
    role:            str
    latitude_raw:    float
    longitude_raw:   float
    qty_min_mt:      int
    qty_max_mt:      int

@router.post("/search")
async def custom_search(payload: SearchPayload):
    """Search with a custom payload — no user_id needed."""
    query_vec = build_query_vector(
        commodity_list=payload.commodity,
        role=payload.role,
        lat=payload.latitude_raw,
        lon=payload.longitude_raw,
        qty_min=payload.qty_min_mt,
        qty_max=payload.qty_max_mt,
    )

    matches = await vector_search(query_vec, exclude_user_id=-1, top_k=TOP_K)

    return {
        "total":   len(matches),
        "results": _fmt_matches(matches),
    }


# ─── GET /recommendations/{user_id}/refresh ───────────────────────────────────

@router.get("/{user_id}/refresh")
async def refresh_recommendations(user_id: int):
    """
    Recomputes the user's IS vector, persists it to Postgres,
    then returns fresh recommendations.
    Useful when encoding logic or boost weights change.
    """
    user = await fetch_user(user_id)

    commodity_list = [c.strip() for c in user["commodity"].split(";")]

    # Rebuild IS vector and persist to Postgres
    candidate_vec = build_candidate_vector(
        commodity_list=commodity_list,
        role=user["role"],
        lat=float(user["latitude_raw"]),
        lon=float(user["longitude_raw"]),
        qty_min=int(user["min_quantity_mt"]),
        qty_max=int(user["max_quantity_mt"]),
    )
    await update_embedding(user_id, candidate_vec)

    # ── OLD: ChromaDB upsert (removed — embedding now lives in Postgres) ──
    # collection = get_chroma_collection()
    # collection.upsert(ids=[str(user_id)], embeddings=[candidate_vec], metadatas=[{...}])

    # Run fresh search
    query_vec = build_query_vector(
        commodity_list=commodity_list,
        role=user["role"],
        lat=float(user["latitude_raw"]),
        lon=float(user["longitude_raw"]),
        qty_min=int(user["min_quantity_mt"]),
        qty_max=int(user["max_quantity_mt"]),
    )
    matches = await vector_search(query_vec, exclude_user_id=user_id, top_k=TOP_K)

    return {
        "user_id":   user_id,
        "refreshed": True,
        "total":     len(matches),
        "results":   _fmt_matches(matches),
    }