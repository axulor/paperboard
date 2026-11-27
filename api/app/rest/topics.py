"""Topics for the web pages. Same logic as the search_topic tool."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.topics import TopicMatch, recent_topics, search_topics, topic_detail
from app.rest.papers import Problem


def build_router(sessions: async_sessionmaker[AsyncSession] | None = None) -> APIRouter:
    router = APIRouter(tags=["topics"])

    @router.get("/topics", summary="Topics like a query, or the newest topics")
    async def list_topics(
        q: Annotated[str | None, Query(description="Words to look for in topic titles")] = None,
        limit: Annotated[int, Query(ge=1, le=50, description="How many topics")] = 20,
    ) -> list[TopicMatch]:
        if sessions is None:
            return []
        if q is not None and q.strip():
            return await search_topics(sessions, q, limit=limit)
        return await recent_topics(sessions, limit=limit)

    @router.get(
        "/topics/{topic_id}",
        summary="One topic: its papers, how many have notes and checked quotes, open questions",
        responses={404: {"model": Problem, "description": "No such topic"}},
    )
    async def get_topic(topic_id: Annotated[int, Path(ge=1)]) -> TopicMatch:
        topic = await topic_detail(sessions, topic_id) if sessions is not None else None
        if topic is None:
            raise HTTPException(status_code=404, detail=f"there is no topic {topic_id}")
        return topic

    return router
