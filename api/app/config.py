from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

EXAMPLE_BLOCKED_WORDS = Path(__file__).parent / "data" / "blocked-words.example.txt"


class Settings(BaseSettings):
    """Runtime settings, read from PAPERBOARD_* environment variables or api/.env."""

    model_config = SettingsConfigDict(env_prefix="PAPERBOARD_", env_file=".env", extra="ignore")

    public_hosts: list[str] = []
    """Host names the server is reached at in staging/production, e.g. ["paperboard.example"].
    Localhost is always allowed. Set as JSON: PAPERBOARD_PUBLIC_HOSTS='["paperboard.example"]'."""

    database_url: SecretStr | None = None
    """PostgreSQL connection URL using the postgresql+psycopg dialect."""

    notes_per_hour: int = 30
    """How many notes one account may post per hour, withdrawn ones included."""

    blocked_words_file: Path = EXAMPLE_BLOCKED_WORDS
    """Word list notes are checked against, one entry per line. The bundled file is a small
    example; a server sets its own list here."""
