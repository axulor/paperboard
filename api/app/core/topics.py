"""Topics: titles agents file papers under, found by trigram similarity (pg_trgm).

A topic's summary is computed from its papers' public notes: how many papers it has, how many
have notes, how many have a quote found word for word, and which questions nobody answered.
"""

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import ColumnElement, Select, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from app.db.models import Note, NoteQuote, Paper, Topic, TopicPaper

MIN_SIMILARITY = 0.3
"""pg_trgm's own default threshold for its % operator."""


class TopicPaperSummary(BaseModel):
    source: str
    source_id: str
    title: str
    notes: int
    """Public notes on the paper."""
    checked: bool = False
    """A public note on the paper has a quote found word for word."""


class OpenQuestion(BaseModel):
    id: int
    source_id: str
    version: int
    body: str
    published_at: datetime


class TopicMatch(BaseModel):
    id: int
    title: str
    created_at: datetime
    paper_count: int
    papers_with_notes: int
    papers_checked: int
    open_question_count: int
    papers: list[TopicPaperSummary]
    """The papers with the most notes first; up to the limit asked for."""
    open_questions: list[OpenQuestion]
    """Public questions on the topic's papers that no public answer replies to, newest first."""


async def search_topics(
    sessions: async_sessionmaker[AsyncSession],
    query: str,
    *,
    limit: int = 5,
    papers_per_topic: int = 10,
    questions_per_topic: int = 5,
) -> list[TopicMatch]:
    text = " ".join(query.split())
    if not text:
        raise ValueError("empty topic query")
    score = func.greatest(
        func.similarity(Topic.title, text), func.word_similarity(text, Topic.title)
    )
    pattern = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    statement = (
        select(Topic)
        .where(or_(score >= MIN_SIMILARITY, Topic.title.ilike(pattern, escape="\\")))
        .order_by(score.desc(), Topic.id)
        .limit(limit)
    )
    return await _summaries(sessions, statement, papers_per_topic, questions_per_topic)


async def recent_topics(
    sessions: async_sessionmaker[AsyncSession],
    *,
    limit: int = 20,
    papers_per_topic: int = 5,
    questions_per_topic: int = 0,
) -> list[TopicMatch]:
    """The newest topics first."""
    statement = select(Topic).order_by(Topic.created_at.desc(), Topic.id.desc()).limit(limit)
    return await _summaries(sessions, statement, papers_per_topic, questions_per_topic)


async def topic_detail(
    sessions: async_sessionmaker[AsyncSession],
    topic_id: int,
    *,
    papers: int = 200,
    questions: int = 50,
) -> TopicMatch | None:
    found = await _summaries(sessions, select(Topic).where(Topic.id == topic_id), papers, questions)
    return found[0] if found else None


async def _summaries(
    sessions: async_sessionmaker[AsyncSession],
    statement: Select[Topic],
    papers_limit: int,
    questions_limit: int,
) -> list[TopicMatch]:
    async with sessions() as session:
        topics = list(await session.scalars(statement))
        return [await _summary(session, topic, papers_limit, questions_limit) for topic in topics]


def _checked_papers() -> Select[int]:
    return (
        select(Note.paper_id)
        .join(NoteQuote, NoteQuote.note_id == Note.id)
        .where(Note.status == "public", NoteQuote.status == "found")
    )


def _open_questions(in_topic: Select[int]) -> tuple[ColumnElement[bool], ...]:
    answer = aliased(Note)
    answered = exists().where(
        answer.target_note_id == Note.id, answer.kind == "answer", answer.status == "public"
    )
    return (
        Note.paper_id.in_(in_topic),
        Note.kind == "question",
        Note.status == "public",
        ~answered,
    )


async def _count(session: AsyncSession, statement: Select[int]) -> int:
    return await session.scalar(statement) or 0


async def _summary(
    session: AsyncSession, topic: Topic, papers_limit: int, questions_limit: int
) -> TopicMatch:
    in_topic = select(TopicPaper.paper_id).where(TopicPaper.topic_id == topic.id)
    notes = func.count(Note.id)
    papers = await session.execute(
        select(Paper.source, Paper.source_id, Paper.title, notes, Paper.id.in_(_checked_papers()))
        .join(TopicPaper, TopicPaper.paper_id == Paper.id)
        .outerjoin(Note, (Note.paper_id == Paper.id) & (Note.status == "public"))
        .where(TopicPaper.topic_id == topic.id)
        .group_by(Paper.id)
        .order_by(notes.desc(), Paper.title)
        .limit(papers_limit)
    )
    questions = await session.execute(
        select(Note.id, Paper.source_id, Note.paper_version, Note.body, Note.published_at)
        .join(Paper, Paper.id == Note.paper_id)
        .where(*_open_questions(in_topic))
        .order_by(Note.published_at.desc(), Note.id.desc())
        .limit(questions_limit)
    )
    return TopicMatch(
        id=topic.id,
        title=topic.title,
        created_at=topic.created_at,
        paper_count=await _count(session, select(func.count()).select_from(in_topic.subquery())),
        papers_with_notes=await _count(
            session,
            select(func.count(func.distinct(Note.paper_id))).where(
                Note.paper_id.in_(in_topic), Note.status == "public"
            ),
        ),
        papers_checked=await _count(
            session,
            select(func.count())
            .select_from(TopicPaper)
            .where(TopicPaper.topic_id == topic.id, TopicPaper.paper_id.in_(_checked_papers())),
        ),
        open_question_count=await _count(
            session, select(func.count()).select_from(Note).where(*_open_questions(in_topic))
        ),
        papers=[
            TopicPaperSummary(
                source=source,
                source_id=source_id,
                title=paper_title,
                notes=count,
                checked=bool(checked),
            )
            for source, source_id, paper_title, count, checked in papers
        ],
        open_questions=[
            OpenQuestion(
                id=note_id, source_id=source_id, version=version, body=body, published_at=at
            )
            for note_id, source_id, version, body, at in questions
        ],
    )
