"""
Application configuration, loaded from environment variables.

Why pydantic-settings instead of raw os.environ calls or a config.ini:
- Type validation happens at startup, not when a route first touches a bad value
- One typed, IDE-autocompletable `settings` object instead of scattered getenv() calls
- Fails fast: the app refuses to boot if a required var is missing or malformed,
  instead of crashing later mid-request in production
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings sourced from environment variables / .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # --- App ---
    environment: str = "development"
    log_level: str = "INFO"

    # --- Postgres ---
    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_host: str
    postgres_port: int = 5432

    # --- Redis ---
    redis_host: str
    redis_port: int = 6379

    # --- JWT ---
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30

    @property
    def database_url(self) -> str:
        """Assembled SQLAlchemy connection string. Never build this string inline elsewhere."""
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"


@lru_cache
def get_settings() -> Settings:
    """
    Returns a cached Settings instance.

    lru_cache makes this a singleton — Settings() is only ever constructed once
    per process, and every part of the app (routes, services, Celery workers)
    shares the same validated config object.
    """
    return Settings()


settings = get_settings()
