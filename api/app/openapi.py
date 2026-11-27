"""Writes the REST API's OpenAPI schema to api/openapi.json; the web generates its types from it.

Run from api/ after changing a REST route or a model it returns:

    uv run python -m app.openapi
"""

import json
import sys
from pathlib import Path

from app.config import Settings
from app.main import create_app

OPENAPI_FILE = Path(__file__).resolve().parents[1] / "openapi.json"


def schema() -> str:
    app = create_app(Settings(database_url=None))
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"


def main(path: Path = OPENAPI_FILE) -> None:
    path.write_text(schema(), encoding="utf-8", newline="\n")
    print(f"wrote {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
