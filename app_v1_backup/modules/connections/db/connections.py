# app/db/connections.py
from fastapi import HTTPException
from sqlalchemy import text
from app.modules.connections.db.postgres import AsyncSessionLocal


# ─── Shared profile shape returned in list responses ─────────────────────────

def _fmt_user(row: dict) -> dict:
    return {
        "user_id":   row["user_id"],
        "role":      row["role"],
        "commodity": row["commodity"],
        "city":      row["city"],
        "state":     row["state"],
        "qty_range": f"{row['min_quantity_mt']}–{row['max_quantity_mt']}mt",
    }


# ─── Follow ───────────────────────────────────────────────────────────────────

async def follow_user(follower_id: int, following_id: int) -> dict:
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("""
            INSERT INTO user_connections (follower_id, following_id)
            VALUES (:follower_id, :following_id)
            ON CONFLICT (follower_id, following_id) DO NOTHING
            RETURNING id
        """), {"follower_id": follower_id, "following_id": following_id})
        await db.commit()
        row = result.fetchone()

    if not row:
        raise HTTPException(status_code=409, detail="Already following this user.")
    return {"status": "following", "following_id": following_id}


async def unfollow_user(follower_id: int, following_id: int) -> dict:
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("""
            DELETE FROM user_connections
            WHERE follower_id = :follower_id AND following_id = :following_id
            RETURNING id
        """), {"follower_id": follower_id, "following_id": following_id})
        await db.commit()
        row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="You are not following this user.")
    return {"status": "unfollowed", "following_id": following_id}


async def get_followers(user_id: int) -> list[dict]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("""
            SELECT u.user_id, u.role, u.commodity, u.city, u.state,
                   u.min_quantity_mt, u.max_quantity_mt,
                   uc.followed_at
            FROM user_connections uc
            JOIN "Users" u ON u.user_id = uc.follower_id
            WHERE uc.following_id = :user_id
            ORDER BY uc.followed_at DESC
        """), {"user_id": user_id})
        rows = result.mappings().all()
    return [
        {**_fmt_user(dict(r)), "followed_at": r["followed_at"]}
        for r in rows
    ]


async def get_following(user_id: int) -> list[dict]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("""
            SELECT u.user_id, u.role, u.commodity, u.city, u.state,
                   u.min_quantity_mt, u.max_quantity_mt,
                   uc.followed_at
            FROM user_connections uc
            JOIN "Users" u ON u.user_id = uc.following_id
            WHERE uc.follower_id = :user_id
            ORDER BY uc.followed_at DESC
        """), {"user_id": user_id})
        rows = result.mappings().all()
    return [
        {**_fmt_user(dict(r)), "followed_at": r["followed_at"]}
        for r in rows
    ]


async def is_following(me: int, target: int) -> bool:
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("""
            SELECT EXISTS(
                SELECT 1 FROM user_connections
                WHERE follower_id = :me AND following_id = :target
            ) AS following
        """), {"me": me, "target": target})
        row = result.mappings().first()
    return row["following"]


# ─── Message Requests ─────────────────────────────────────────────────────────

async def send_message_request(sender_id: int, receiver_id: int) -> dict:
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("""
            INSERT INTO message_requests (sender_id, receiver_id)
            VALUES (:sender_id, :receiver_id)
            ON CONFLICT (sender_id, receiver_id) DO NOTHING
            RETURNING id, status, sent_at
        """), {"sender_id": sender_id, "receiver_id": receiver_id})
        await db.commit()
        row = result.fetchone()

    if not row:
        raise HTTPException(status_code=409, detail="Message request already sent.")
    return {"id": row[0], "status": row[1], "sent_at": row[2]}


async def withdraw_message_request(sender_id: int, receiver_id: int) -> dict:
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("""
            DELETE FROM message_requests
            WHERE sender_id = :sender_id
              AND receiver_id = :receiver_id
              AND status = 'pending'
            RETURNING id
        """), {"sender_id": sender_id, "receiver_id": receiver_id})
        await db.commit()
        row = result.fetchone()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="No pending request found to withdraw."
        )
    return {"status": "withdrawn", "receiver_id": receiver_id}


async def respond_to_request(request_id: int, me: int, action: str) -> dict:
    """Shared handler for accept and decline. action must be 'accepted' or 'declined'."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("""
            UPDATE message_requests
            SET status = :action, acted_at = NOW()
            WHERE id = :request_id
              AND receiver_id = :me
              AND status = 'pending'
            RETURNING id
        """), {"action": action, "request_id": request_id, "me": me})
        await db.commit()
        row = result.fetchone()

    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Request not found, already acted on, or you are not the receiver."
        )
    return {"id": request_id, "status": action}


async def get_received_requests(me: int) -> list[dict]:
    """Pending inbox — requests waiting on me to accept or decline."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("""
            SELECT mr.id, mr.sender_id, mr.status, mr.sent_at,
                   u.user_id,u.role, u.commodity, u.city, u.state,
                   u.min_quantity_mt, u.max_quantity_mt
            FROM message_requests mr
            JOIN "Users" u ON u.user_id = mr.sender_id
            WHERE mr.receiver_id = :me AND mr.status = 'pending'
            ORDER BY mr.sent_at DESC
        """), {"me": me})
        rows = result.mappings().all()
    return [
        {
            "request_id": r["id"],
            "from":        _fmt_user(dict(r)),
            "sent_at":     r["sent_at"],
        }
        for r in rows
    ]


async def get_sent_requests(me: int) -> list[dict]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("""
            SELECT mr.id, mr.receiver_id, mr.status, mr.sent_at, mr.acted_at,
                   u.user_id,u.role, u.commodity, u.city, u.state,
                   u.min_quantity_mt, u.max_quantity_mt
            FROM message_requests mr
            JOIN "Users" u ON u.user_id = mr.receiver_id
            WHERE mr.sender_id = :me
            ORDER BY mr.sent_at DESC
        """), {"me": me})
        rows = result.mappings().all()
    return [
        {
            "request_id": r["id"],
            "to":          _fmt_user(dict(r)),
            "status":      r["status"],
            "sent_at":     r["sent_at"],
            "acted_at":    r["acted_at"],
        }
        for r in rows
    ]


# ─── Search ───────────────────────────────────────────────────────────────────

async def search_users(
    me: int,
    q: str | None,
    role: str | None,
    commodity: str | None,
    city: str | None,
) -> list[dict]:
    """
    Filtered user search. `q` does a broad ILIKE across city, state, commodity, role.
    All filters are optional and stack with AND logic.
    Returns at most 50 results.
    """
    conditions = ["u.user_id != :me"]
    params: dict = {"me": me}

    if q:
        conditions.append("""
            (u.city ILIKE :q
             OR u.state ILIKE :q
             OR u.commodity ILIKE :q
             OR u.role ILIKE :q)
        """)
        params["q"] = f"%{q}%"

    if role:
        conditions.append("u.role = :role")
        params["role"] = role

    if commodity:
        conditions.append("u.commodity ILIKE :commodity")
        params["commodity"] = f"%{commodity}%"

    if city:
        conditions.append("u.city ILIKE :city")
        params["city"] = f"%{city}%"

    where = " AND ".join(conditions)
    async with AsyncSessionLocal() as db:
        result = await db.execute(text(f"""
            SELECT user_id, role, commodity, city, state,
                   min_quantity_mt, max_quantity_mt
            FROM "Users" u
            WHERE {where}
            ORDER BY u.city
            LIMIT 50
        """), params)
        rows = result.mappings().all()
    return [_fmt_user(dict(r)) for r in rows]


async def search_suggestions(q: str) -> list[dict]:
    """
    Fuzzy 'did you mean?' suggestions using pg_trgm trigram similarity.
    Searches across city, commodity, and role. Returns top 8 closest matches.
    Requires pg_trgm extension (installed by migrate_connections.py).
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("""
            SELECT user_id, role, commodity, city, state,
                   min_quantity_mt, max_quantity_mt,
                   GREATEST(
                       similarity(city, :q),
                       similarity(commodity, :q),
                       similarity(role, :q)
                   ) AS score
            FROM "Users"
            WHERE similarity(city, :q)      > 0.15
               OR similarity(commodity, :q) > 0.15
               OR similarity(role, :q)      > 0.15
            ORDER BY score DESC
            LIMIT 8
        """), {"q": q})
        rows = result.mappings().all()
    return [
        {**_fmt_user(dict(r)), "score": round(float(r["score"]), 3)}
        for r in rows
    ]
