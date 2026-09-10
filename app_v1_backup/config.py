from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str
    SECRET_KEY: str
    ENVIRONMENT: str = "production"
    
    class Config:
        env_file = ".env"

settings = Settings()