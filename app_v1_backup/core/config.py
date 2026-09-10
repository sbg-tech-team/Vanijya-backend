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

    # news_new pipeline — provider fetch + LLM enrichment
    GNEWS_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None

    # Sentry — error + performance monitoring
    SENTRY_DSN: Optional[str] = None            # from sentry.io project settings; unset = disabled
    ENVIRONMENT: str = "development"            # "development" | "staging" | "production"
    SENTRY_TRACES_SAMPLE_RATE: float = 0.1      # fraction of requests traced for performance (0.1 = 10%; raise locally if needed)
    SENTRY_PROFILES_SAMPLE_RATE: float = 0.1    # fraction of traced requests profiled (function-level timing)

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
