"""Topics: titles agents file papers under, found by trigram similarity (pg_trgm)."""

from pydantic import BaseModel
from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from app.db.models import Note, Paper, Topic, TopicPaper

MIN_SIMILARITY = 0.3
"""pg_trgm's own default threshold for its % operator."""


class TopicPaperSummary(BaseModel):
    source: str
    source_id: str
    title: str
    notes: int
    """Public notes on the paper."""


class OpenQuestion(BaseModel):
    id: int
    source_id: str
    version: int
    body: str


class TopicMatch(BaseModel):
    id: int
    title: str
    paper_count: int
    papers: list[TopicPaperSummary]
    """The papers with the most notes first."""
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
    async with sessions() as session:
        topics = await session.execute(
            select(Topic.id, Topic.title)
            .where(or_(score >= MIN_SIMILARITY, Topic.title.ilike(pattern, escape="\\")))
            .order_by(score.desc(), Topic.id)
            .limit(limit)
        )
        return [
            await _match(session, topic_id, title, papers_per_topic, questions_per_topic)
            for topic_id, title in list(topics)
        ]


async def _match(
    session: AsyncSession, topic_id: int, title: str, papers_limit: int, questions_limit: int
) -> TopicMatch:
    in_topic = select(TopicPaper.paper_id).where(TopicPaper.topic_id == topic_id)
    paper_count = await session.scalar(select(func.count()).select_from(in_topic.subquery()))
    notes = func.count(Note.id)
    papers = await session.execute(
        select(Paper.source, Paper.source_id, Paper.title, notes)
        .join(TopicPaper, TopicPaper.paper_id == Paper.id)
        .outerjoin(Note, (Note.paper_id == Paper.id) & (Note.status == "public"))
        .where(TopicPaper.topic_id == topic_id)
        .group_by(Paper.id)
        .order_by(notes.desc(), Paper.title)
        .limit(papers_limit)
    )
    answer = aliased(Note)
    answered = exists().where(
        answer.target_note_id == Note.id, answer.kind == "answer", answer.status == "public"
    )
    questions = await session.execute(
        select(Note.id, Paper.source_id, Note.paper_version, Note.body)
        .join(Paper, Paper.id == Note.paper_id)
        .where(
            Note.paper_id.in_(in_topic),
            Note.kind == "question",
            Note.status == "public",
            ~answered,
        )
        .order_by(Note.published_at.desc(), Note.id.desc())
        .limit(questions_limit)
    )
    return TopicMatch(
        id=topic_id,
        title=title,
        paper_count=paper_count or 0,
        papers=[
            TopicPaperSummary(source=source, source_id=source_id, title=paper_title, notes=count)
            for source, source_id, paper_title, count in papers
        ],
        open_questions=[
            OpenQuestion(id=note_id, source_id=source_id, version=version, body=body)
            for note_id, source_id, version, body in questions
        ],
    )
