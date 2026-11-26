"""Short plain-text answers for agents: a few lines per item, no JSON."""

from app.core.papers import PaperReport
from app.sources import PaperRecord, SearchQuery, SearchResult, SortOrder
from app.sources.base import VersionInfo

ABSTRACT_CHARS = 300
AUTHORS_SHOWN = 3


def _authors(names: list[str]) -> str:
    if len(names) <= AUTHORS_SHOWN:
        return ", ".join(names)
    return f"{', '.join(names[:AUTHORS_SHOWN])} et al. ({len(names)} authors)"


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return f"{cut} …"


def _record(number: int, record: PaperRecord) -> str:
    category = f" · {record.primary_category}" if record.primary_category else ""
    lines = [
        f"{number}. {record.title}",
        f"   arXiv {record.source_id}v{record.version} · submitted "
        f"{record.published.date().isoformat()}{category} · {_authors(record.authors)}",
        f"   {_shorten(record.abstract, ABSTRACT_CHARS)}",
    ]
    return "\n".join(lines)


def render_search(query: SearchQuery, result: SearchResult) -> str:
    order = "newest first" if query.sort is SortOrder.RECENT else "most relevant first"
    span = ""
    if query.submitted_from or query.submitted_to:
        start = query.submitted_from.isoformat() if query.submitted_from else "…"
        end = query.submitted_to.isoformat() if query.submitted_to else "…"
        span = f", submitted {start} to {end}"
    if not result.records:
        return (
            f"arXiv: no papers found for `{query.text}`{span}. "
            "Try fewer or broader English terms, or a wider date range."
        )
    first = result.offset + 1
    last = result.offset + len(result.records)
    header = (
        f"arXiv: {result.total} papers for `{query.text}` ({order}{span}). Showing {first}-{last}."
    )
    body = "\n\n".join(_record(first + i, r) for i, r in enumerate(result.records))
    more = f"\n\nMore: call again with offset={last}." if last < result.total else ""
    return f"{header}\n\n{body}{more}"


def _versions(versions: list[VersionInfo]) -> str:
    items = [f"v{v.version} {v.submitted.date().isoformat()}" for v in versions]
    if len(items) > 6:
        items = [*items[:3], "…", *items[-2:]]
    return ", ".join(items)


def render_paper(report: PaperReport) -> str:
    facts = report.facts
    latest = f"{facts.source_id}v{facts.latest_version}"
    lines = [
        facts.title,
        f"arXiv {facts.source_id} · latest version v{facts.latest_version} · "
        f"{len(facts.versions)} version{'s' if len(facts.versions) != 1 else ''}: "
        f"{_versions(facts.versions)}",
        f"Withdrawn: yes ({facts.comment})" if facts.withdrawn else "Withdrawn: no",
        f"License: {facts.license or 'not stated'}",
    ]
    if facts.comment and not facts.withdrawn:
        lines.append(f"Authors' comment: {facts.comment}")
    if facts.journal_ref:
        lines.append(f"Journal: {facts.journal_ref}")
    if facts.doi:
        lines.append(f"DOI: {facts.doi}")

    if report.code_links:
        links = "; ".join(f"{link.url} ({link.kind})" for link in report.code_links)
        lines.append(f"Code, models and data linked from the paper: {links}")
    elif report.full_text_url:
        lines.append(
            "Code, models and data linked from the paper: none in the metadata or full text"
        )
    else:
        lines.append("Code, models and data linked from the paper: none in the metadata")

    read = f"Read: https://arxiv.org/abs/{latest}"
    if report.full_text_url and report.full_text_format:
        read += f" · full text ({report.full_text_format.upper()}): {report.full_text_url}"
    lines.append(read)
    if report.full_text_problem:
        lines.append(f"Full text could not be read: {report.full_text_problem}")
    return "\n".join(lines)
