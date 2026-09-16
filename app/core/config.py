from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str          # postgresql+asyncpg://...
    SYNC_DATABASE_URL: str     # postgresql+psycopg2://...
    REDIS_URL: str = "redis://localhost:6379/0"

    # Auth — Firebase Phone Auth (OTP sent client-side, backend only verifies ID token)
    GOOGLE_SERVICE_ACCOUNT_JSON: Optional[str] = None  # set in production; dev falls back to service.json

    # JWT token lifetimes
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 600     # 1 hour
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30       # 30 days

    # Gemini
    GEMINI_API_KEY: Optional[str] = None

    # News pipeline — GNews (ingest) + Groq (enrich).
    # These MUST be declared here: extra="ignore" below means an undeclared name
    # raises AttributeError at the call site rather than failing at startup.
    GNEWS_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None

    # Stream Video & Audio (calling). Absent => calling returns 503 rather than
    # erroring deep in a request.
    STREAM_API_KEY: Optional[str] = None
    STREAM_API_SECRET: Optional[str] = None

    # Sentry — absent disables error tracking entirely (no-op, no failure).
    SENTRY_DSN: Optional[str] = None
    SENTRY_TRACES_SAMPLE_RATE: float = 0.2
    ENVIRONMENT: str = "development"

    # Calling spend ceilings, in participant-minutes. Stream audio is $0.30 per
    # 1,000, so the monthly default (~$90) sits inside Stream's $100 free credit.
    # Raise deliberately — this is the hard stop on a surprise bill.
    CALLS_PER_USER_DAILY_MINUTES: int = 600
    CALLS_PLATFORM_MONTHLY_MINUTES: int = 300_000

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
