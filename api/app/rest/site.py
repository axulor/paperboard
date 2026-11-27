"""What the web pages need about the site as a whole."""

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.sitemap import Sitemap, sitemap


def build_router(sessions: async_sessionmaker[AsyncSession] | None = None) -> APIRouter:
    router = APIRouter(tags=["site"])

    @router.get("/sitemap", summary="Papers with public notes, and topics, for sitemap.xml")
    async def get_sitemap() -> Sitemap:
        if sessions is None:
            return Sitemap(papers=[], topics=[])
        return await sitemap(sessions)

    return router
