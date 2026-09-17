import logging
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

# Defaults to require, so production and any managed database keep TLS. A local
# or CI Postgres has no TLS at all and simply cannot be connected to otherwise,
# which is what blocked integration tests from ever running.
_SSLMODE = os.getenv("DB_SSLMODE", "require")

# Pool sizing was never set, so this ran on SQLAlchemy's default of 5 + 10
# overflow: 15 connections per worker, total. Load testing hit
# "QueuePool limit of size 5 overflow 10 reached" long before CPU or memory
# mattered.
#
# It bites hardest in production, where the database is a round trip away: a
# request holds its connection for the whole trip, so the ceiling is roughly
# pool / latency. At ~1.2 s to Tokyo, 15 connections is about 12 requests per
# second no matter how big the instance is.
#
# Supabase's transaction pooler (port 6543) is built for many short-lived
# connections, so a larger app-side pool is safe. Tune with env vars rather than
# a code change.
_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "20"))
_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))

engine = create_engine(
    settings.SYNC_DATABASE_URL,
    connect_args={"sslmode": _SSLMODE},
    pool_pre_ping=True,
    pool_size=_POOL_SIZE,
    max_overflow=_MAX_OVERFLOW,
    # Fail fast instead of parking a request for 30 s behind an exhausted pool.
    pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "10")),
    # Recycle before any pooler or firewall silently drops an idle connection.
    pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "1800")),
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Which database this process actually talks to. Credentials are never logged.
# Worth one line at boot: "table does not exist" errors are impossible to
# diagnose without knowing whether the app and your psql session agree on the
# target, and that question cost real time once already.
logging.getLogger(__name__).info(
    "DB engine -> host=%s port=%s db=%s sslmode=%s pool=%d+%d",
    engine.url.host, engine.url.port, engine.url.database, _SSLMODE,
    _POOL_SIZE, _MAX_OVERFLOW,
)
