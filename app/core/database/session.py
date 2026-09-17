import logging
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

# Which database this process actually talks to. Credentials are never logged.
# Worth one line at boot: "table does not exist" errors are impossible to
# diagnose without knowing whether the app and your psql session agree on the
# target, and that question cost real time once already.
logging.getLogger(__name__).info(
    "DB engine -> host=%s port=%s db=%s sslmode=%s",
    engine.url.host, engine.url.port, engine.url.database, _SSLMODE,
)
