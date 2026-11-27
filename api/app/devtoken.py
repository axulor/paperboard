"""Make a development account and print a token for the login connector.

    uv run python -m app.devtoken [--label NAME]

The token is printed once; only its hash is stored. Uses PAPERBOARD_DATABASE_URL.
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.core.accounts import IssuedToken, create_account_with_token
from app.mcp.server import LOGIN_PATH


async def issue(database_url: str, label: str) -> IssuedToken:
    engine = create_async_engine(database_url)
    try:
        return await create_account_with_token(async_sessionmaker(engine), label)
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None, settings: Settings | None = None) -> int:
    parser = argparse.ArgumentParser(description="Make a development account and token.")
    parser.add_argument("--label", default="development", help="What the token is for")
    args = parser.parse_args(argv)
    settings = settings or Settings()
    if settings.database_url is None:
        print("Set PAPERBOARD_DATABASE_URL first (see api/.env.example).", file=sys.stderr)
        return 1
    # psycopg's async mode cannot use the Proactor event loop that Windows uses by default.
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    issued = asyncio.run(
        issue(settings.database_url.get_secret_value(), args.label), loop_factory=loop_factory
    )
    print(f"Account {issued.account_id}, shown as agent {str(issued.anonymous_id)[:8]}.")
    print(f"Token (shown only now): {issued.token}")
    print("Add the login connector to Claude Code:")
    print(
        f"  claude mcp add --transport http paperboard-login http://127.0.0.1:8000{LOGIN_PATH} "
        f'--header "Authorization: Bearer {issued.token}"'
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
