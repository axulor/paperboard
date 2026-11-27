from pathlib import Path

from app.openapi import OPENAPI_FILE, main, schema


def test_openapi_file_is_current() -> None:
    assert OPENAPI_FILE.read_text(encoding="utf-8") == schema(), (
        "api/openapi.json is out of date: run `uv run python -m app.openapi` in api/"
    )


def test_main_writes_the_schema(tmp_path: Path) -> None:
    path = tmp_path / "openapi.json"
    main(path)
    assert path.read_text(encoding="utf-8") == schema()
