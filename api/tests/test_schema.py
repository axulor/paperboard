from io import StringIO
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

INITIAL_TABLES = ("accounts", "papers", "topics", "topic_papers", "notes", "note_quotes")


def test_initial_migration_emits_sql_for_its_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPERBOARD_DATABASE_URL", "postgresql+psycopg://schema.invalid/paperboard")
    output = StringIO()
    config = Config(Path(__file__).resolve().parents[1] / "alembic.ini", output_buffer=output)

    command.upgrade(config, "0001", sql=True)
    upgrade_sql = output.getvalue()
    output.seek(0)
    output.truncate()
    command.downgrade(config, "0001:base", sql=True)
    downgrade_sql = output.getvalue()

    assert upgrade_sql.index("CREATE EXTENSION IF NOT EXISTS pg_trgm") < upgrade_sql.index(
        "CREATE INDEX ix_topics_title_trgm"
    )
    assert "USING gin (title gin_trgm_ops)" in upgrade_sql
    for table in INITIAL_TABLES:
        assert f"CREATE TABLE {table} (" in upgrade_sql
        assert f"DROP TABLE {table};" in downgrade_sql
    assert downgrade_sql.index("DROP TABLE note_quotes;") < downgrade_sql.index("DROP TABLE notes;")
    assert downgrade_sql.index("DROP TABLE notes;") < downgrade_sql.index("DROP TABLE papers;")
    assert "DROP EXTENSION" not in downgrade_sql
