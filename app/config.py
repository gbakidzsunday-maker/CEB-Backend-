"""
Central configuration for the Secure CBE backend.

All values can be overridden with environment variables, which is how
you will set secrets (SECRET_KEY especially) on Render.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Secure Computer-Based Examination System"

    # SQLite file. On Render, point this at a path on a mounted persistent
    # disk (e.g. /var/data/cbe.db) if you want data to survive redeploys.
    DATABASE_URL: str = "sqlite:///./data/cbe.db"

    # IMPORTANT: override this with a real random secret in production
    # (Render -> Environment -> add SECRET_KEY).
    SECRET_KEY: str = "change-this-secret-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Account lockout policy (mitigates brute-force / credential-stuffing)
    MAX_FAILED_LOGIN_ATTEMPTS: int = 5
    LOCKOUT_MINUTES: int = 15

    # Simple in-memory rate limiting (mitigates DoS on hot endpoints)
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    RATE_LIMIT_MAX_REQUESTS: int = 30

    # CORS - set to your deployed frontend origin(s) in production
    CORS_ORIGINS: list[str] = ["*"]


settings = Settings()
