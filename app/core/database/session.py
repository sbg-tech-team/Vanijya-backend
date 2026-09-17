import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

# Defaults to require, so production and any managed database keep TLS. A local
# or CI Postgres has no TLS at all and simply cannot be connected to otherwise,
# which is what blocked integration tests from ever running.
_SSLMODE = os.getenv("DB_SSLMODE", "require")

engine = create_engine(
    settings.SYNC_DATABASE_URL,
    connect_args={"sslmode": _SSLMODE},
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
