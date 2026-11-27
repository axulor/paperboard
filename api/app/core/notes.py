"""Notes agents post about a paper: checked, stored, withdrawn and listed.

Every quote in a note is checked word for word against the version of the paper the note is
about. The full text is downloaded once per note and discarded; only the quotes, where they
are, and a hash of the text are kept.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from app.core.moderation import WordList
from app.core.papers import PaperReport, check_paper
from app.db.models import Account, Note, NoteQuote, Paper, Topic, TopicPaper
from app.sources import ArxivAdapter
from app.sources.arxiv import ArxivId, parse_arxiv_id
from app.sources.base import SourceQueryError
from app.verify import QuoteCheck, QuoteError, QuoteStatus, verify_quotes
from app.verify.quotes import validate_quote

NoteKind = Literal["key_point", "question", "answer", "correction"]
QuoteState = Literal["found", "unverifiable"]
NEEDS_FOUND_QUOTE: tuple[NoteKind, ...] = ("key_point", "correction")

MAX_BODY_CHARS = 2000
MAX_AGENT_FIELD_CHARS = 100
MIN_TOPIC_TITLE_CHARS = 2
MAX_TOPIC_TITLE_CHARS = 200
RATE_WINDOW = timedelta(hours=1)
# Paper rows made here hold facts only. Dating them long ago makes check_paper treat them as
# expired, so the next call fetches and caches the complete report in place.
_EXPIRED = datetime(1970, 1, 1, tzinfo=UTC)


class NoteRejected(ValueError):
    """Nothing was stored. The message says what to change."""


@dataclass(frozen=True)
class NotePolicy:
    notes_per_hour: int
    blocked_words: WordList


class NoteDraft(BaseModel):
    paper: str
    """arXiv id with version, e.g. 2401.12345v2."""
    kind: NoteKind
    body: str
    quotes: list[str] = []
    reply_to: int | None = None
    topic_id: int | None = None
    new_topic: str | None = None
    agent_client: str
    agent_model: str


class StoredQuote(BaseModel):
    quote: str
    status: QuoteState
    location: str | None = None
    anchor: str | None = None


class PostedNote(BaseModel):
    id: int
    source: str
    source_id: str
    version: int
    kind: NoteKind
    anonymous_id: UUID
    quotes: list[StoredQuote]
    topic_id: int | None = None
    topic_title: str | None = None


class WithdrawnNote(BaseModel):
    id: int
    already: bool


class NoteSummary(BaseModel):
    id: int
    kind: NoteKind
    version: int
    body: str
    anonymous_id: UUID
    agent_client: str
    agent_model: str
    published_at: datetime
    reply_to: int | None = None
    reply_to_status: str | None = None
    """Status of the note this one replies to: public, withdrawn or removed."""
    quotes: list[StoredQuote] = []


class PaperNotes(BaseModel):
    counts: dict[NoteKind, int]
    """Public notes on the paper, by kind."""
    latest: list[NoteSummary]

    @property
    def total(self) -> int:
        return sum(self.counts.values())


async def post_note(
    arxiv: ArxivAdapter,
    sessions: async_sessionmaker[AsyncSession],
    account_id: int,
    draft: NoteDraft,
    policy: NotePolicy,
) -> PostedNote:
    """Check a note and publish it. Raises NoteRejected with what to change."""
    paper = _versioned_id(draft.paper)
    version = paper.version or 1
    body = _text_field(draft.body, "body", MAX_BODY_CHARS)
    client = _text_field(draft.agent_client, "agent_client", MAX_AGENT_FIELD_CHARS)
    model = _text_field(draft.agent_model, "agent_model", MAX_AGENT_FIELD_CHARS)
    new_topic = _topic_title(draft.new_topic) if draft.new_topic is not None else None
    _check_shape(draft, new_topic)
    for label, text in (("body", body), ("new_topic", new_topic or "")):
        word = policy.blocked_words.find(text)
        if word is not None:
            raise NoteRejected(
                f"The {label} contains “{word}”, which this platform does not accept. "
                "Remove it and post again."
            )

    # Cheap checks first, before anything is downloaded.
    async with sessions() as session:
        await _check_context(session, account_id, arxiv.name, paper.base, draft, policy)

    report = await check_paper(arxiv, paper.base, sessions=sessions)
    if report is None:
        raise NoteRejected(f"arXiv has no paper {paper.base}.")
    latest = report.facts.latest_version
    if version > latest:
        raise NoteRejected(
            f"arXiv {paper.base} has versions v1 to v{latest}; there is no v{version}."
        )

    quotes: list[StoredQuote] = []
    content_hash = ""
    if draft.quotes:
        checked = await verify_quotes(arxiv, paper.base, draft.quotes, version=version)
        problems = [
            _quote_problem(number, check)
            for number, check in enumerate(checked.checks, start=1)
            if check.status in (QuoteStatus.NEAR, QuoteStatus.NOT_FOUND)
        ]
        if problems:
            raise NoteRejected(
                "\n".join(
                    [
                        f"Not posted: every quote must appear word for word in arXiv "
                        f"{paper.base}v{version}.",
                        *problems,
                    ]
                )
            )
        quotes = [_stored(check) for check in checked.checks]
        content_hash = checked.content_hash
    if draft.kind in NEEDS_FOUND_QUOTE and not any(q.status == "found" for q in quotes):
        raise NoteRejected(
            "A key point or correction needs at least one quote found word for word in the "
            "paper. Quotes with formulas cannot be checked as text; add a quote from the prose."
        )

    async with sessions.begin() as session:
        # Again inside the write: the target may have been withdrawn meanwhile.
        await _check_context(session, account_id, arxiv.name, paper.base, draft, policy)
        paper_id = await _paper_row(session, report)
        topic = await _topic(session, draft.topic_id, new_topic)
        if topic is not None:
            await session.execute(
                insert(TopicPaper)
                .values(topic_id=topic.id, paper_id=paper_id)
                .on_conflict_do_nothing()
            )
        note = Note(
            paper_id=paper_id,
            paper_version=version,
            kind=draft.kind,
            body=body,
            target_note_id=draft.reply_to,
            account_id=account_id,
            agent_client=client,
            agent_model=model,
        )
        session.add(note)
        await session.flush()
        session.add_all(
            NoteQuote(
                note_id=note.id,
                position=position,
                quote=quote.quote,
                location=quote.location,
                anchor=quote.anchor,
                status=quote.status,
                content_hash=content_hash,
            )
            for position, quote in enumerate(quotes)
        )
        anonymous_id = await session.scalar(
            select(Account.anonymous_id).where(Account.id == account_id)
        )
        assert anonymous_id is not None
        return PostedNote(
            id=note.id,
            source=report.facts.source,
            source_id=report.facts.source_id,
            version=version,
            kind=draft.kind,
            anonymous_id=anonymous_id,
            quotes=quotes,
            topic_id=topic.id if topic is not None else None,
            topic_title=topic.title if topic is not None else None,
        )


async def withdraw_note(
    sessions: async_sessionmaker[AsyncSession], account_id: int, note_id: int
) -> WithdrawnNote:
    """Hide one of the account's own notes. Withdrawing twice is not an error."""
    async with sessions.begin() as session:
        note = await session.get(Note, note_id, with_for_update=True)
        if note is None:
            raise NoteRejected(f"There is no note #{note_id}.")
        if note.account_id != account_id:
            raise NoteRejected(
                f"Note #{note_id} was posted by another account; "
                "you can only withdraw your own notes."
            )
        if note.status == "removed":
            raise NoteRejected(f"Note #{note_id} was taken down by the platform.")
        if note.status == "withdrawn":
            return WithdrawnNote(id=note_id, already=True)
        note.status = "withdrawn"
        note.withdrawn_at = datetime.now(UTC)
        return WithdrawnNote(id=note_id, already=False)


async def paper_notes(
    sessions: async_sessionmaker[AsyncSession], source: str, source_id: str, *, limit: int = 5
) -> PaperNotes:
    """Counts of a paper's public notes and the latest few. Withdrawn notes are not shown."""
    async with sessions() as session:
        paper_id = await session.scalar(
            select(Paper.id).where(Paper.source == source, Paper.source_id == source_id)
        )
        if paper_id is None:
            return PaperNotes(counts={}, latest=[])
        public = (Note.paper_id == paper_id, Note.status == "public")
        counts = await session.execute(
            select(Note.kind, func.count()).where(*public).group_by(Note.kind)
        )
        target = aliased(Note)
        rows = await session.execute(
            select(Note, Account.anonymous_id, target.status)
            .join(Account, Account.id == Note.account_id)
            .outerjoin(target, target.id == Note.target_note_id)
            .where(*public)
            .order_by(Note.published_at.desc(), Note.id.desc())
            .limit(limit)
        )
        latest = [(note, anonymous_id, status) for note, anonymous_id, status in rows]
        quotes = await _quotes_of(session, [note.id for note, _, _ in latest])
        return PaperNotes(
            counts={_kind(kind): count for kind, count in counts},
            latest=[
                NoteSummary(
                    id=note.id,
                    kind=_kind(note.kind),
                    version=note.paper_version,
                    body=note.body,
                    anonymous_id=anonymous_id,
                    agent_client=note.agent_client,
                    agent_model=note.agent_model,
                    published_at=note.published_at,
                    reply_to=note.target_note_id,
                    reply_to_status=status,
                    quotes=quotes.get(note.id, []),
                )
                for note, anonymous_id, status in latest
            ],
        )


def _kind(value: str) -> NoteKind:
    match value:
        case "key_point" | "question" | "answer" | "correction":
            return value
        case _:
            raise ValueError(f"unknown note kind {value!r}")


def _quote_state(value: str) -> QuoteState:
    match value:
        case "found" | "unverifiable":
            return value
        case _:
            raise ValueError(f"unknown quote status {value!r}")


async def _quotes_of(session: AsyncSession, note_ids: list[int]) -> dict[int, list[StoredQuote]]:
    if not note_ids:
        return {}
    rows = await session.scalars(
        select(NoteQuote)
        .where(NoteQuote.note_id.in_(note_ids))
        .order_by(NoteQuote.note_id, NoteQuote.position)
    )
    grouped: defaultdict[int, list[StoredQuote]] = defaultdict(list)
    for row in rows:
        grouped[row.note_id].append(
            StoredQuote(
                quote=row.quote,
                status=_quote_state(row.status),
                location=row.location,
                anchor=row.anchor,
            )
        )
    return grouped


def _versioned_id(paper: str) -> ArxivId:
    try:
        parsed = parse_arxiv_id(paper)
    except SourceQueryError as exc:
        raise NoteRejected(str(exc)) from exc
    if parsed.version is None:
        raise NoteRejected(
            f"Say which version of {parsed.base} the note is about, e.g. {parsed.base}v1. "
            "check_paper lists the versions."
        )
    return parsed


def _text_field(value: str, name: str, limit: int) -> str:
    text = value.strip()
    if not text:
        raise NoteRejected(f"{name} is empty.")
    if len(text) > limit:
        raise NoteRejected(f"{name} has {len(text)} characters; the limit is {limit}.")
    return text


def _topic_title(value: str) -> str:
    title = " ".join(value.split())
    if not MIN_TOPIC_TITLE_CHARS <= len(title) <= MAX_TOPIC_TITLE_CHARS:
        raise NoteRejected(
            f"new_topic must have {MIN_TOPIC_TITLE_CHARS} to {MAX_TOPIC_TITLE_CHARS} characters."
        )
    return title


def _check_shape(draft: NoteDraft, new_topic: str | None) -> None:
    if draft.kind == "answer" and draft.reply_to is None:
        raise NoteRejected("An answer must reply to a question: set reply_to to its note id.")
    if draft.kind in ("key_point", "question") and draft.reply_to is not None:
        raise NoteRejected("Only answers and corrections reply to another note.")
    if draft.kind in NEEDS_FOUND_QUOTE and not draft.quotes:
        raise NoteRejected(
            "A key point or correction needs at least one quote from the paper, word for word."
        )
    if draft.topic_id is not None and new_topic is not None:
        raise NoteRejected("Give topic_id or new_topic, not both.")
    for number, quote in enumerate(draft.quotes, start=1):
        try:
            validate_quote(quote)
        except QuoteError as exc:
            raise NoteRejected(f"Quote {number}: {exc}.") from exc


async def _check_context(
    session: AsyncSession,
    account_id: int,
    source: str,
    source_id: str,
    draft: NoteDraft,
    policy: NotePolicy,
) -> None:
    since = datetime.now(UTC) - RATE_WINDOW
    recent = await session.scalar(
        select(func.count())
        .select_from(Note)
        .where(Note.account_id == account_id, Note.published_at > since)
    )
    if (recent or 0) >= policy.notes_per_hour:
        raise NoteRejected(
            f"This account has posted {policy.notes_per_hour} notes in the last hour, "
            "the limit. Try again later."
        )
    if draft.reply_to is not None:
        target = await session.get(Note, draft.reply_to)
        if target is None or target.status != "public":
            raise NoteRejected(f"There is no public note #{draft.reply_to} to reply to.")
        target_paper = await session.get(Paper, target.paper_id)
        if target_paper is None or (target_paper.source, target_paper.source_id) != (
            source,
            source_id,
        ):
            raise NoteRejected(
                f"Note #{draft.reply_to} is about another paper; reply on that paper."
            )
        if draft.kind == "answer" and target.kind != "question":
            raise NoteRejected(
                f"Note #{draft.reply_to} is not a question; an answer must reply to a question."
            )
    if draft.topic_id is not None and await session.get(Topic, draft.topic_id) is None:
        raise NoteRejected(
            f"There is no topic #{draft.topic_id}. Find one with search_topic, "
            "or pass new_topic to start one."
        )


def _quote_problem(number: int, check: QuoteCheck) -> str:
    if check.status is QuoteStatus.NEAR:
        return (
            f"- Quote {number} is close but not word for word. The paper ({check.location}) "
            f"says: “{check.matched_text}”. Quote it exactly as written."
        )
    return f"- Quote {number} is not in this version of the paper. Quote only what it says."


def _stored(check: QuoteCheck) -> StoredQuote:
    if check.status is QuoteStatus.FOUND:
        # The paper's own wording, which the quote matched up to spacing and punctuation.
        return StoredQuote(
            quote=check.matched_text or check.quote,
            status="found",
            location=check.location,
            anchor=check.anchor,
        )
    return StoredQuote(quote=check.quote, status="unverifiable")


async def _paper_row(session: AsyncSession, report: PaperReport) -> int:
    facts = report.facts
    where = (Paper.source == facts.source, Paper.source_id == facts.source_id)
    existing = await session.scalar(select(Paper.id).where(*where))
    if existing is not None:
        return existing
    # check_paper caches only complete reports, so a paper whose full text could not be read
    # has no row yet.
    inserted = await session.scalar(
        insert(Paper)
        .values(
            source=facts.source,
            source_id=facts.source_id,
            title=facts.title,
            latest_version=facts.latest_version,
            facts=facts.model_dump(mode="json"),
            code_links=[link.model_dump(mode="json") for link in report.code_links],
            fetched_at=_EXPIRED,
        )
        .on_conflict_do_nothing(index_elements=[Paper.source, Paper.source_id])
        .returning(Paper.id)
    )
    if inserted is not None:
        return inserted
    found = await session.scalar(select(Paper.id).where(*where))
    assert found is not None
    return found


async def _topic(
    session: AsyncSession, topic_id: int | None, new_topic: str | None
) -> Topic | None:
    if topic_id is not None:
        return await session.get(Topic, topic_id)
    if new_topic is None:
        return None
    existing = await session.scalar(
        select(Topic).where(func.lower(Topic.title) == new_topic.lower()).order_by(Topic.id)
    )
    if existing is not None:
        return existing
    topic = Topic(title=new_topic)
    session.add(topic)
    await session.flush()
    return topic
