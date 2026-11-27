"""Handle readers' reports from the command line. Uses PAPERBOARD_DATABASE_URL.

uv run python -m app.moderate list           reports nobody has handled, oldest first
uv run python -m app.moderate remove NOTE    take a note down and close its reports
uv run python -m app.moderate keep NOTE      close a note's reports and keep it
"""

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable, Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.core.reports import ReportRejected, keep_note, open_reports, take_down

Sessions = async_sessionmaker[AsyncSession]
Action = Callable[[Sessions], Awaitable[str]]


async def list_reports(sessions: Sessions) -> str:
    reports = await open_reports(sessions)
    if not reports:
        return "No open reports."
    lines: list[str] = []
    for report in reports:
        lines.append(
            f"Report {report.id} · note {report.note_id} ({report.note_kind}, "
            f"{report.note_status}) on arXiv {report.source_id}v{report.version} · "
            f"{report.reason} · {report.created_at.date().isoformat()}"
        )
        if report.detail:
            lines.append(f"  Reader: {' '.join(report.detail.split())}")
        lines.append(f"  Note: {' '.join(report.note_body.split())[:300]}")
    return "\n".join(lines)


async def remove(sessions: Sessions, note_id: int) -> str:
    closed = await take_down(sessions, note_id)
    return f"Took down note {note_id}; closed {closed} report(s)."


async def keep(sessions: Sessions, note_id: int) -> str:
    closed = await keep_note(sessions, note_id)
    return f"Kept note {note_id}; closed {closed} report(s)."


async def run(database_url: str, action: Action) -> str:
    engine = create_async_engine(database_url)
    try:
        return await action(async_sessionmaker(engine))
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None, settings: Settings | None = None) -> int:
    parser = argparse.ArgumentParser(description="Handle readers' reports on notes.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="Reports nobody has handled, oldest first")
    for name, text in (("remove", "Take a note down"), ("keep", "Keep a note")):
        command = commands.add_parser(name, help=text)
        command.add_argument("note", type=int, help="Note id")
    args = parser.parse_args(argv)
    settings = settings or Settings()
    if settings.database_url is None:
        print("Set PAPERBOARD_DATABASE_URL first (see api/.env.example).", file=sys.stderr)
        return 1
    note: int = getattr(args, "note", 0)
    actions: dict[str, Action] = {
        "list": list_reports,
        "remove": lambda sessions: remove(sessions, note),
        "keep": lambda sessions: keep(sessions, note),
    }
    # psycopg's async mode cannot use the Proactor event loop that Windows uses by default.
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    try:
        output = asyncio.run(
            run(settings.database_url.get_secret_value(), actions[args.command]),
            loop_factory=loop_factory,
        )
    except ReportRejected as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
