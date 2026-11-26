from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, read from PAPERBOARD_* environment variables or api/.env."""

    model_config = SettingsConfigDict(env_prefix="PAPERBOARD_", env_file=".env", extra="ignore")

    public_hosts: list[str] = []
    """Host names the server is reached at in staging/production, e.g. ["paperboard.example"].
    Localhost is always allowed. Set as JSON: PAPERBOARD_PUBLIC_HOSTS='["paperboard.example"]'."""

    database_url: SecretStr | None = None
    """PostgreSQL connection URL using the postgresql+psycopg dialect."""
