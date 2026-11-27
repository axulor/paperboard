"""What the sitemap lists: papers with public notes, and topics."""

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Note, Paper, Topic, TopicPaper

MAX_URLS = 50_000
"""The most URLs one sitemap file may hold."""


class SitemapPaper(BaseModel):
    source: str
    source_id: str
    updated: datetime
    """When its newest public note was posted."""


class SitemapTopic(BaseModel):
    id: int
    updated: datetime
    """When the topic was made, or a public note on one of its papers was posted, if later."""


class Sitemap(BaseModel):
    papers: list[SitemapPaper]
    topics: list[SitemapTopic]


async def sitemap(sessions: async_sessionmaker[AsyncSession]) -> Sitemap:
    newest_note = func.max(Note.published_at)
    async with sessions() as session:
        papers = await session.execute(
            select(Paper.source, Paper.source_id, newest_note)
            .join(Note, Note.paper_id == Paper.id)
            .where(Note.status == "public")
            .group_by(Paper.id)
            .order_by(newest_note.desc())
            .limit(MAX_URLS)
        )
        topic_notes = (
            select(TopicPaper.topic_id, newest_note.label("newest"))
            .join(Note, Note.paper_id == TopicPaper.paper_id)
            .where(Note.status == "public")
            .group_by(TopicPaper.topic_id)
            .subquery()
        )
        updated = func.greatest(
            Topic.created_at, func.coalesce(topic_notes.c.newest, Topic.created_at)
        )
        topics = await session.execute(
            select(Topic.id, updated)
            .outerjoin(topic_notes, topic_notes.c.topic_id == Topic.id)
            .order_by(updated.desc())
            .limit(MAX_URLS)
        )
        return Sitemap(
            papers=[
                SitemapPaper(source=source, source_id=source_id, updated=at)
                for source, source_id, at in papers
            ],
            topics=[SitemapTopic(id=topic_id, updated=at) for topic_id, at in topics],
        )
